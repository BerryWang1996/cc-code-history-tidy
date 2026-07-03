# 分组剪贴板 + 同名合并 + 撤回/重置 + 多语言 设计

日期：2026-07-03
状态：用户已批准（"ok，做吧"）

## 背景

会话级剪贴板交互已上线（见 2026-07-03-clipboard-interaction-design.md）。本轮补齐：

1. 分组级复制/剪切/粘贴（跨账户迁移整组）。
2. 移动/复制分组到目标账户时按显示名自动合并同名分组。
3. 撤回（Ctrl+Z）/ 重做（Ctrl+Y）/ 重置到扫描后初始状态。
4. 副本分组归属修复：复制的副本执行后应出现在粘贴时所在的分组，而非一律未分组。
5. 界面多语言（中文/English），默认跟随系统语言，可切换并持久化。

Execute 前一切模拟、按 root 全量备份、失败全回滚的安全模型不变。

## A. 分组级剪贴板

- `_stash_clipboard` 扩展：选中项全为会话 → 会话剪贴板（现行为）；全为分组 →
  分组剪贴板；混合选择 → 拒绝并提示。Ungrouped（`code_group_id ==
  "ungrouped"`）不可复制/剪切。
- 剪贴板状态增加 `clipboard_kind: "session" | "group" | None`。
- 粘贴分组时目标解析为**账户**：粘贴到分组/会话上取其所属账户；粘贴到账户上
  即该账户。
- **剪切分组粘贴**：分组树项整体移动到目标账户末尾（Ungrouped 之前）；若目标
  账户已有同名分组 → 组内会话逐个并入现有组尾，空壳不保留。粘贴回原账户且无
  同名合并对象 = 移回原位置（无操作等价）。粘贴后清空剪贴板、恢复变淡。
- **复制分组粘贴**：在目标账户创建幽灵分组（`STAGED_MODE_ROLE="copy"` 标记在
  组项上，组内为幽灵会话项）；若目标账户已有同名分组 → 不建新组，幽灵会话直接
  并入现有组尾。复制剪贴板可重复粘贴。
- 幽灵分组不可再复制/剪切；右键提供"撤销此暂存副本"（整组移除）。
- **拖拽分组到另一个账户 = 剪切+粘贴**：`_move_groups_to_target` 检测目标账户
  变化时走同一 `merge_group_into_account` 路径（含同名合并）；账户内拖拽排序
  行为不变。
- 剪切分组的变淡样式作用于组项及其全部子项。

## B. 同名合并规则

- 判定：`label.strip()` 相等（区分大小写）。
- 合并动作只发生在"分组进入另一个账户"时（粘贴或拖拽）。
- 合并后被并入的会话遵循普通会话规则：跨账户/根 → 待移入徽标 + MOVE 计划；
  幽灵 → COPY 计划。

## C. 副本分组归属（id 映射）

- `MigrationResult` 增加 `session_id_mapping: tuple[tuple[str, str], ...]`
  （旧 id → 新 id；MOVE 时为空）。`_build_copy_pairs` 已生成新 id，随 pair
  返回即可。
- `execute_plan`：
  1. 迁移循环里收集每个 COPY 批次的 id 映射。
  2. 为每个幽灵会话项记录（旧 id、目标 root、目标 code_group_id）；布局写入
     阶段把 `code:<新id>` 追加进目标 root 的 assignments 与该组 order 末尾
     （目标组为 Ungrouped 时不写）。
  3. 布局保存函数在写 assignments/order 的同时，把树中已知的组名合并写入该
     root 配置的 `customGroups`（id+name，保留原有条目），保证跨根移动后组名
     在工具内可读回。Claude Desktop 对 config 中组名的读取不做保证（LevelDB
     限制照旧，README 已述）。
- 由于布局写入依赖迁移结果，`有幽灵副本时布局写入必须在迁移之后`（现有顺序
  已满足：先迁移后写布局）。

## D. 撤回 / 重做 / 重置

- 新模块 `cc_history_tidy/tree_state.py`：
  - `capture_tree_state(tree) -> TreeState`：结构化快照（账户序列 → 组序列
    （code_group_id、label、group_id、ghost 标记）→ 会话序列（ClaudeSession
    payload、ghost 标记））。账户项自身不可变，快照只记录其 UserRole 数据与
    文案。
  - `restore_tree_state(tree, state)`：清空并重建树项（复用
    `_new_code_group_item` 与会话项构造逻辑）。
- `SessionTreeWidget` 增加 `undo_stack`/`redo_stack`（上限 50）；
  `push_undo_snapshot()` 在每个树变更操作前调用（paste_to、dropEvent 成功
  分支、remove_ghost_item、分组合并）。undo/redo 时同时清空剪贴板（避免悬挂
  引用）。
- 快捷键：Ctrl+Z 撤回、Ctrl+Y 重做。工具栏按钮：撤回/重做（栈空置灰）。
- **重置**按钮：`MainWindow.reset_staged_changes()` —— 用缓存的
  `self.accounts` 重建树（不读盘），清空剪贴板与两个栈，状态栏提示。
- Execute 成功或重新扫描后清空两个栈。
- 状态栏：任何树变更后刷新暂存汇总（"已暂存 N 移动 + M 复制（Ctrl+Z 可撤
  回）"；无暂存时不覆盖操作提示）。

## E. 多语言

- 新模块 `cc_history_tidy/i18n.py`：
  - `LANGS = {"zh": {...}, "en": {...}}`，`tr(key, **kwargs) -> str`（缺键回
    退 zh 文案）；`set_language(code)`、`current_language()`。
  - `detect_default_language()`：settings.json 的 `language`（"zh"/"en"）优
    先；否则 `QLocale.system().name()` 以 `zh` 开头 → zh，否则 en。
  - 设置文件 `~/.claude-desktop-migrator/settings.json`：`{"language": "zh"}`；
    读写容错（损坏时按系统语言）。
- 所有用户可见字符串（按钮、表头、tooltip、状态栏、对话框、徽标文本、右键菜
  单）迁移到 i18n 键。徽标文本（待移入/⊕ 待复制）也随语言切换，但树数据角色
  判断不依赖显示文本（ghost 用 STAGED_MODE_ROLE，测试断言改用角色/键而非硬编
  码中文）。
- UI：工具栏右侧 `QComboBox`（中文 / English）。切换时：写 settings、
  `set_language`、调用 `retranslate_ui()` 刷新静态文案并重刷树徽标/状态栏。
- 测试断言策略：用 `tr(key)` 生成期望值，避免语言切换破坏测试。

## F. 其他操作逻辑完善

- 粘贴目标为幽灵项：插到其后（同组），与普通会话一致。
- 多选（跨组）会话剪切→粘贴保持选择时的可视顺序（现有 `_visual_path` 排序已
  保证，回归测试覆盖）。
- 混合选择（会话+分组）复制/剪切 → 状态栏提示"请只选择会话或只选择分组"。

## 测试计划

- 组剪切→粘贴另一账户（无同名/有同名合并两种）；组复制→粘贴（幽灵组、并入同
  名组）；Ungrouped 不可剪切；混合选择拒绝；拖拽组跨账户=剪切粘贴+合并。
- 副本落组：单会话复制→执行→新 id 出现在目标组 assignments/order；整组复制
  →执行→全部新 id 落组;跨根时组名写入目标 config customGroups。
- undo/redo/reset：粘贴后 Ctrl+Z 恢复、Ctrl+Y 重做、重置回初始；Execute 后栈
  清空。
- i18n：默认语言检测（模拟 settings 与系统 locale）、切换后按钮文案变化、设
  置持久化。
- 全量旧测试回归。

## 不在范围内

- 两种以上语言；组重命名/新建/删除；LevelDB 写入。
