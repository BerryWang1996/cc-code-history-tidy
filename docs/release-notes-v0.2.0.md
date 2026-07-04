# CC Code History Tidy v0.2.0

Windows 桌面工具：在本机多个 Claude 账号之间迁移、复制和整理 Claude Desktop「Code 模式」的对话记录。
A Windows desktop tool for migrating, copying and organizing Claude Desktop **Code-mode** conversations between local Claude accounts.

---

## 使用说明（中文）

### 下载与运行

1. 下载附件 `cc-code-history-tidy.exe`（免安装，单文件，双击运行）。
2. 界面语言默认跟随系统，可在右上角下拉框切换（简体中文 / 繁體中文 / English / 日本語 / 한국어 / Español / Français / Deutsch / Русский）。

### 基本流程

1. **扫描**：载入本机所有 Claude 安装（含 MSIX、`%APPDATA%\Claude`、`Claude-3p` 网关版）中的 Code 会话，按「账户 → 分组 → 对话」树形展示。
2. **整理（全部是模拟，磁盘不会有任何改动）**：
   - 右键对话或**整个分组** → 复制 (`Ctrl+C`) / 剪切 (`Ctrl+X`)；右键目标位置 → 粘贴 (`Ctrl+V`)；`Esc` 清空剪贴板
   - **拖拽 = 移动**；把分组移动/复制到已有**同名分组**的账户时自动合并
   - 剪切的条目变淡；跨账户移动显示蓝色「待移入」；复制产生绿色「⊕ 待复制」副本（右键可单独撤销）
   - `Ctrl+Z` 撤回、`Ctrl+Y` 重做（50 步）；**重置**一键回到扫描后状态
3. **预览**：查看即将发生的移动/复制/布局变更数量，不写盘。
4. **执行**：弹出确认框，确认后才真正写入。执行前自动对**所有涉及目录**做完整备份，任何一步失败会全部回滚。**备份**按钮可查看和恢复历史备份。

### 注意事项

- 执行前需关闭 Claude Desktop（注意：Claude Code CLI 也是 `claude.exe`，开着终端会话时执行按钮同样会被禁用）。
- 复制出的副本会获得**新的会话 ID** 并落在你粘贴到的分组里；原对话及其分组不受影响。
- 侧栏分组的**组名**存储在 Claude Desktop 的内部缓存（LevelDB）中，本工具无法安全写入该缓存。整理分组后请重启 Claude Desktop 核对侧栏；对话文件本身的迁移不受此限制影响。
- 所有备份保存在 `%USERPROFILE%\.claude-desktop-migrator\backups`。

## Usage (English)

1. Download the attached `cc-code-history-tidy.exe` (portable, single file).
2. **Scan** loads Code-mode sessions from every local Claude install and shows an Account → Group → Conversation tree.
3. Organize — **everything is simulated until Execute**: right-click conversations or whole groups to Copy/Cut (`Ctrl+C`/`Ctrl+X`), right-click a target to Paste (`Ctrl+V`); drag = move; groups merge automatically into a same-name group; `Ctrl+Z`/`Ctrl+Y` undo/redo; Reset returns to the freshly-scanned state.
4. **Preview** shows what would happen; **Execute** asks for confirmation, backs up every involved directory first, and rolls everything back on failure. Restore any backup from the **Backups** dialog.
5. Close Claude Desktop before executing. Copies get a fresh session id and land in the group you pasted them into. Group *names* live in Claude Desktop's internal cache which this tool cannot write — restart Claude Desktop and verify the sidebar after regrouping.

---

## v0.2.0 变更 / Changes

- 九种界面语言，默认跟随系统语言，可随时切换并持久化 / Nine UI languages with system-language default
- 分组级复制/剪切/粘贴，跨账户迁移整组 / Group-level clipboard operations across accounts
- 同名分组自动合并 / Automatic merge into same-name groups
- 撤回 (Ctrl+Z) / 重做 (Ctrl+Y) / 重置 / Undo, redo and reset for all staged edits
- 副本执行后落在粘贴的分组，组名一并写入配置 / Copies land in their pasted group with labels persisted
- 全部操作模拟直到执行确认；按目录全量备份 + 全量回滚 / Fully simulated staging with per-root backup and rollback
- 修复同一物理目录（MSIX 目录联接）被扫描两次导致的账户重复 / De-duplicated junctioned session roots
- 时间列人性化显示、界面细节完善 / Readable timestamps and UI polish

**测试 / Tests:** 115 automated tests passing.
