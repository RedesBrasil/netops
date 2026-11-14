# SKILL — Hooks do Claude Code (guarda NetOps)

`guard-netops.sh` é um hook `PreToolUse` (Bash) do Claude Code. Ele bloqueia:

- **alteração em equipamento via `session.py run|exec` sem `change.py begin`**, ou seja, backup antes de alterar
  (ver `AGENTS.md`).

## Onde fica e por quê

O script e o modelo `claude-settings.json` ficam aqui, em `scripts/engine/hooks/`, porque esse caminho entra no
pacote de release e é aceito pelo atualizador de **qualquer** versão instalada. Um pacote com arquivos em
`.claude/hooks/` seria recusado (`protected_path`) pelos atualizadores até a 2.3.1.

O `.claude/settings.json` do projeto só aponta para cá:
`bash "$CLAUDE_PROJECT_DIR/scripts/engine/hooks/guard-netops.sh"`.

## Instalar ou conferir

```bash
python3 scripts/engine/hooks/install_claude_hooks.py           # mescla o hook no .claude/settings.json
python3 scripts/engine/hooks/install_claude_hooks.py --check   # exit 1 se faltar ou estiver desatualizado
```

A mesclagem é idempotente. Ela preserva tudo o que já existe no `settings.json` (tema, permissões e outros hooks) e
troca entradas antigas que apontavam para `.claude/hooks/guard-netops.sh`. O `install.sh` roda isso na
instalação e no reparo.

Teste: `scripts/engine/ui/tests/test_claude_hooks.py`.
