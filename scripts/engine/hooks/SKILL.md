# SKILL — Claude Code hooks (NetOps guard)

`guard-netops.sh` is a Claude Code `PreToolUse` (Bash) hook. It blocks:

- **changes to equipment via `session.py run|exec` without `change.py begin`**, i.e. backup before changing
  (see `AGENTS.md`).

## Where it lives and why

The script and the `claude-settings.json` template live here, in `scripts/engine/hooks/`, because this path is part of
the release package and is accepted by the updater of **any** installed version. A package with files in
`.claude/hooks/` would be rejected (`protected_path`) by updaters up to 2.3.1.

The project's `.claude/settings.json` only points here:
`bash "$CLAUDE_PROJECT_DIR/scripts/engine/hooks/guard-netops.sh"`.

## Install or check

```bash
python3 scripts/engine/hooks/install_claude_hooks.py           # merges the hook into .claude/settings.json
python3 scripts/engine/hooks/install_claude_hooks.py --check   # exit 1 if missing or outdated
```

The merge is idempotent. It preserves everything already in `settings.json` (theme, permissions and other hooks) and
replaces old entries that pointed to `.claude/hooks/guard-netops.sh`. `install.sh` runs it on
install and on repair.

Test: `scripts/engine/ui/tests/test_claude_hooks.py`.
