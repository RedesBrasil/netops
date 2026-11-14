"""Hooks do Claude Code (scripts/engine/hooks): distribuição, mesclagem do settings e bloqueio."""
from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

import deps  # noqa: F401  (bootstrap de scripts/engine no sys.path)

from update.common import distributed

ROOT = Path(__file__).resolve().parents[4]
HOOKS = ROOT / "scripts" / "engine" / "hooks"
sys.path.insert(0, str(HOOKS))
import install_claude_hooks as ich  # noqa: E402

TEMPLATE = json.loads((HOOKS / "claude-settings.json").read_text(encoding="utf-8"))
GUARD = "scripts/engine/hooks/guard-netops.sh"


def test_hook_files_ship_in_release_package_accepted_by_any_updater():
    # scripts/ é aceito pelo distributed() de todas as versões; .claude/hooks/ não seria (protected_path).
    for rel in (GUARD, "scripts/engine/hooks/claude-settings.json", "scripts/engine/hooks/install_claude_hooks.py"):
        assert distributed(rel), rel
    assert os.access(ROOT / GUARD, os.X_OK)
    cmd = TEMPLATE["hooks"]["PreToolUse"][0]["hooks"][0]["command"]
    assert GUARD in cmd and "$CLAUDE_PROJECT_DIR" in cmd


def test_merge_adds_hook_and_preserves_user_settings():
    user = {"theme": "dark", "permissions": {"allow": ["Bash(ls:*)"]},
            "hooks": {"PreToolUse": [{"matcher": "Edit", "hooks": [{"type": "command", "command": "meu.sh"}]}],
                      "Stop": [{"hooks": [{"type": "command", "command": "fim.sh"}]}]}}
    merged, changed = ich.merge(json.loads(json.dumps(user)), TEMPLATE)
    assert changed
    assert merged["theme"] == "dark" and merged["permissions"] == user["permissions"]
    assert merged["hooks"]["Stop"] == user["hooks"]["Stop"]
    pre = merged["hooks"]["PreToolUse"]
    assert pre[0] == user["hooks"]["PreToolUse"][0] and pre[1] == TEMPLATE["hooks"]["PreToolUse"][0]
    again, changed2 = ich.merge(merged, TEMPLATE)
    assert not changed2 and again == merged


def test_merge_rewrites_legacy_hook_path():
    legacy = json.loads(json.dumps(TEMPLATE))
    legacy["hooks"]["PreToolUse"][0]["hooks"][0]["command"] = 'bash "$CLAUDE_PROJECT_DIR/.claude/hooks/guard-netops.sh"'
    merged, changed = ich.merge(legacy, TEMPLATE)
    assert changed and merged["hooks"]["PreToolUse"] == TEMPLATE["hooks"]["PreToolUse"]


def test_cli_creates_settings_and_check(tmp_path):
    script = HOOKS / "install_claude_hooks.py"
    check = [sys.executable, str(script), "--root", str(tmp_path), "--check"]
    assert subprocess.run(check, capture_output=True).returncode == 1
    assert subprocess.run([sys.executable, str(script), "--root", str(tmp_path)], capture_output=True).returncode == 0
    data = json.loads((tmp_path / ".claude/settings.json").read_text())
    assert data["hooks"] == TEMPLATE["hooks"]
    assert subprocess.run(check, capture_output=True).returncode == 0


def _guard(command: str, *, script=GUARD) -> int:
    payload = json.dumps({"tool_input": {"command": command}})
    return subprocess.run(["bash", str(ROOT / script)], input=payload, text=True, capture_output=True,
                          env={**os.environ, "CLAUDE_PROJECT_DIR": str(ROOT)}).returncode


def test_guard_blocks_dangerous_and_allows_harmless():
    dangerous = "unl_wrapper -a " + "fix" + "permissions"   # montado p/ não acionar o próprio hook
    for script in (GUARD, ".claude/hooks/guard-netops.sh"):   # caminho novo + shim de compatibilidade
        assert _guard(dangerous, script=script) == 2
        assert _guard("ls -la", script=script) == 0
