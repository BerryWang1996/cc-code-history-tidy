from __future__ import annotations

import json
from pathlib import Path

LANGS: dict[str, dict[str, str]] = {
    "zh": {
        "app.title": "CC Code History Tidy",
        "app.initial_status": "点击 扫描 载入 Claude Desktop Code 会话，然后用 复制/剪切/粘贴 或拖拽整理。",
        "btn.scan": "扫描",
        "btn.preview": "预览",
        "btn.execute": "执行",
        "btn.backups": "备份",
        "btn.undo": "撤回",
        "btn.redo": "重做",
        "btn.reset": "重置",
        "header.tree": "账户 / Code 分组 / 对话",
        "header.updated": "更新时间",
        "tree.group_type": "Code 分组",
        "tree.sessions_count": "{n} 个会话",
        "tree.ungrouped": "未分组",
        "badge.move": "待移入",
        "badge.copy": "⊕ 待复制",
        "menu.copy": "复制\tCtrl+C",
        "menu.cut": "剪切\tCtrl+X",
        "menu.paste": "粘贴\tCtrl+V",
        "menu.undo_ghost": "撤销此暂存副本",
        "status.scan_failed": "扫描失败：{exc}",
        "status.loaded": "已加载 {n} 个会话（{root}）",
        "status.dry_run": "预览：{moves} 个移动、{copies} 个复制；布局更新：{layout}。（未写入磁盘）",
        "status.no_backups": "在 {path} 未找到备份。",
        "status.restored": "已恢复备份 {name}。",
        "status.close_claude_first": "请先关闭 Claude Desktop。",
        "status.scan_first": "请先扫描。",
        "status.no_staged": "没有暂存的修改。",
        "status.cancelled": "已取消，未做任何更改。",
        "status.backup_failed": "备份失败，执行已取消：{exc}",
        "status.exec_failed_rolled_back": "执行失败，已全部回滚：{exc}",
        "status.exec_failed_partial": "执行失败：{exc}。有 {n} 个目录回滚失败（{details}），请从 {path} 手动恢复。",
        "status.executed": "执行完成：写入 {copied} 个文件，移除 {removed} 个源文件。",
        "status.staged_summary": "已暂存 {moves} 个移动 + {copies} 个复制。按 执行 写入磁盘（Ctrl+Z 可撤回）。",
        "status.copied_n": "已复制 {n} 项——右键目标位置粘贴 (Ctrl+V)。",
        "status.cut_n": "已剪切 {n} 项——右键目标位置粘贴 (Ctrl+V)。",
        "status.select_first": "请先选中要复制/剪切的对话或分组。",
        "status.mixed_selection": "请只选择对话，或只选择分组。",
        "status.paste_empty": "剪贴板为空——先复制 (Ctrl+C) 或剪切 (Ctrl+X)。",
        "status.paste_target_invalid": "只能粘贴到分组、账户或对话上。",
        "status.ghost_removed": "已撤销暂存副本。",
        "status.clipboard_cleared": "已清空剪贴板。",
        "status.reset_done": "已恢复到扫描后的初始状态。",
        "status.nothing_to_undo": "没有可撤回的操作。",
        "status.nothing_to_redo": "没有可重做的操作。",
        "status.undo_done": "已撤回。",
        "status.redo_done": "已重做。",
        "status.language_changed": "语言已切换为中文。",
        "tooltip.execute_disabled": "请先关闭 Claude Desktop / Claude Code Desktop 再执行。注意：Claude Code CLI 也以 claude.exe 运行，会触发此检查。",
        "tooltip.execute_enabled": "执行暂存的变更（会先弹出确认框）。",
        "dlg.confirm_title": "确认执行",
        "dlg.summary_head": "将",
        "dlg.summary_move": "移动 {n} 个对话",
        "dlg.summary_copy": "创建 {n} 个副本",
        "dlg.summary_layout": "更新分组布局",
        "dlg.summary_join": "、",
        "dlg.summary_tail": "。执行前会自动备份所有涉及的目录。继续？",
        "dlg.claude_running_title": "Claude 正在运行",
        "dlg.claude_running_body": "请先关闭 Claude Desktop 再执行迁移。",
        "dlg.backups_title": "备份",
        "dlg.restore_selected": "恢复所选",
        "dlg.restore_title": "恢复备份",
        "dlg.restore_body": "恢复备份 {name}？\n\n这将替换以下目录的会话树：\n{path}",
        "dlg.restore_running_body": "请先关闭 Claude Desktop / Claude Code Desktop 再恢复备份。",
    },
    "en": {
        "app.title": "CC Code History Tidy",
        "app.initial_status": "Click Scan to load Claude Desktop Code sessions, then organize with copy/cut/paste or drag.",
        "btn.scan": "Scan",
        "btn.preview": "Preview",
        "btn.execute": "Execute",
        "btn.backups": "Backups",
        "btn.undo": "Undo",
        "btn.redo": "Redo",
        "btn.reset": "Reset",
        "header.tree": "Account / Code group / Conversation",
        "header.updated": "Updated",
        "tree.group_type": "Code group",
        "tree.sessions_count": "{n} session(s)",
        "tree.ungrouped": "Ungrouped",
        "badge.move": "pending move",
        "badge.copy": "⊕ pending copy",
        "menu.copy": "Copy\tCtrl+C",
        "menu.cut": "Cut\tCtrl+X",
        "menu.paste": "Paste\tCtrl+V",
        "menu.undo_ghost": "Undo this staged copy",
        "status.scan_failed": "Scan failed: {exc}",
        "status.loaded": "Loaded {n} session(s) from {root}",
        "status.dry_run": "Preview: {moves} move(s), {copies} copy(ies); layout update: {layout}. (nothing written)",
        "status.no_backups": "No backups found in {path}.",
        "status.restored": "Restored backup {name}.",
        "status.close_claude_first": "Close Claude Desktop first.",
        "status.scan_first": "Scan first.",
        "status.no_staged": "No staged changes.",
        "status.cancelled": "Cancelled; nothing was changed.",
        "status.backup_failed": "Backup failed; execution cancelled: {exc}",
        "status.exec_failed_rolled_back": "Execution failed and was fully rolled back: {exc}",
        "status.exec_failed_partial": "Execution failed: {exc}. Rollback incomplete for {n} root(s) ({details}); restore manually from {path}.",
        "status.executed": "Done: wrote {copied} file(s), removed {removed} source file(s).",
        "status.staged_summary": "Staged: {moves} move(s) + {copies} copy(ies). Press Execute to write (Ctrl+Z to undo).",
        "status.copied_n": "Copied {n} item(s) — right-click a target to paste (Ctrl+V).",
        "status.cut_n": "Cut {n} item(s) — right-click a target to paste (Ctrl+V).",
        "status.select_first": "Select conversations or groups to copy/cut first.",
        "status.mixed_selection": "Select only conversations or only groups.",
        "status.paste_empty": "Clipboard is empty — copy (Ctrl+C) or cut (Ctrl+X) first.",
        "status.paste_target_invalid": "Paste onto a group, account or conversation.",
        "status.ghost_removed": "Staged copy undone.",
        "status.clipboard_cleared": "Clipboard cleared.",
        "status.reset_done": "Restored to the state right after scanning.",
        "status.nothing_to_undo": "Nothing to undo.",
        "status.nothing_to_redo": "Nothing to redo.",
        "status.undo_done": "Undone.",
        "status.redo_done": "Redone.",
        "status.language_changed": "Language switched to English.",
        "tooltip.execute_disabled": "Close Claude Desktop / Claude Code Desktop before executing. Note: the Claude Code CLI also runs as claude.exe and triggers this check.",
        "tooltip.execute_enabled": "Execute staged changes (a confirmation dialog is shown first).",
        "dlg.confirm_title": "Confirm execution",
        "dlg.summary_head": "This will ",
        "dlg.summary_move": "move {n} conversation(s)",
        "dlg.summary_copy": "create {n} copy(ies)",
        "dlg.summary_layout": "update the group layout",
        "dlg.summary_join": ", ",
        "dlg.summary_tail": ". All involved directories are backed up first. Continue?",
        "dlg.claude_running_title": "Claude is running",
        "dlg.claude_running_body": "Close Claude Desktop before migrating.",
        "dlg.backups_title": "Backups",
        "dlg.restore_selected": "Restore selected",
        "dlg.restore_title": "Restore backup",
        "dlg.restore_body": "Restore backup {name}?\n\nThis replaces the sessions tree at:\n{path}",
        "dlg.restore_running_body": "Close Claude Desktop / Claude Code Desktop before restoring a backup.",
    },
}

_current_language = "zh"


def set_language(code: str) -> None:
    global _current_language
    _current_language = code if code in LANGS else "zh"


def current_language() -> str:
    return _current_language


def tr(key: str, **kwargs) -> str:
    table = LANGS.get(_current_language, LANGS["zh"])
    template = table.get(key) or LANGS["zh"][key]
    return template.format(**kwargs) if kwargs else template


def detect_default_language(settings_path: Path) -> str:
    try:
        data = json.loads(Path(settings_path).read_text(encoding="utf-8"))
        language = data.get("language") if isinstance(data, dict) else None
        if language in LANGS:
            return language
    except (OSError, json.JSONDecodeError):
        pass
    try:
        from PySide6.QtCore import QLocale

        return "zh" if QLocale.system().name().startswith("zh") else "en"
    except Exception:  # pragma: no cover - PySide missing in exotic envs
        return "zh"


def save_language(code: str, settings_path: Path) -> None:
    settings_path = Path(settings_path)
    data: dict[str, object] = {}
    try:
        loaded = json.loads(settings_path.read_text(encoding="utf-8"))
        if isinstance(loaded, dict):
            data = loaded
    except (OSError, json.JSONDecodeError):
        pass
    data["language"] = code
    settings_path.parent.mkdir(parents=True, exist_ok=True)
    settings_path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
