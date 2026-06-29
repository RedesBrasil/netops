---
id: vault
name: Cofre de Credenciais
type: script
runtime: python
description: Criptografa as senhas de network/credentials.yaml com uma senha-mestra e destranca a sessão.
env: [NETOPS_VAULT_KEY]
---

## O que faz

Criptografa em repouso os campos secretos (`password`, `secret`) de
`network/credentials.yaml`, deixando cada valor como `enc.v1:<token>` (a estrutura e os
`username` continuam legíveis). A descriptografia acontece **só em memória**, durante a
sessão, depois de destrancar com a **senha-mestra**.

- **Criptografia:** Fernet (AES-128-CBC + HMAC). **KDF:** Argon2id (fallback Scrypt).
- **Sessão:** a chave derivada (nunca a senha) fica num arquivo `0600` em RAM
  (`$XDG_RUNTIME_DIR/netops/session.key`, tmpfs). Re-bloqueia por **inatividade (15 min,
  configurável)**, no `lock`, ou no logout. Como vive entre processos, funciona tanto pro
  operador quanto pros agentes de IA (cada comando deles roda num shell novo).
- **Modo terminal-puro (`--env`):** opcional; a chave vai numa variável de ambiente e morre
  ao fechar o terminal — mas não é compartilhada com os scripts executados pela IA.

## Quando usar

- Uma vez, para migrar `credentials.yaml` de texto puro para criptografado (`init` + `encrypt`).
- No início de cada sessão de trabalho, para destrancar (`unlock`).
- Para rotacionar uma senha (`set`) ou trocar a senha-mestra (`change-password`).

A IA **não** roda `init`/`unlock`/`set`/`change-password` (precisam de senha digitada num TTY
real). A IA pode rodar `status` e `lock`, e os scripts de acesso usam a chave da sessão
automaticamente.

## Como usar

```bash
python scripts/engine/vault/cli.py <subcomando> [--file PATH]
```

| Subcomando | Faz | Pergunta (oculta) |
|------------|-----|-------------------|
| `init` | Cria o bloco `vault:` (salt + verifier) | senha-mestra ×2 |
| `encrypt` (`migrate`) | Texto puro → `enc.v1:` (idempotente; `--dry-run` simula) | senha-mestra |
| `set --cred N --field {password,secret}` | Define/rotaciona um campo | senha + valor |
| `unlock [--ttl SEG] [--env]` | Destranca a sessão | senha-mestra |
| `lock` | Tranca a sessão (apaga o cache) | — |
| `status` | Estado do cofre/sessão (exit 0=destrancado, 1=trancado) | — |
| `change-password` | Troca a senha e re-criptografa tudo | senha antiga + nova ×2 |

## Setup

Sem dependência nova: `cryptography` (já em `requirements.txt`, presente via `paramiko`) e
`pyyaml`. Requer `$XDG_RUNTIME_DIR` (tmpfs) para o cache em RAM; sem ele, cai para `/run/user/<uid>`
e, por último, `/tmp` (com aviso de que pode ser disco).

## Exemplos

```bash
# Migração inicial (uma vez)
cp network/credentials.yaml ~/creds.backup.$(date +%F).yaml   # backup fora do repo
python scripts/engine/vault/cli.py init
python scripts/engine/vault/cli.py encrypt --dry-run
python scripts/engine/vault/cli.py encrypt

# Dia a dia
python scripts/engine/vault/cli.py unlock      # destranca (digita a senha-mestra, sem eco)
python scripts/engine/lib/inventory.py --list  # funciona mesmo trancado (não descriptografa)
# ... agentes/scripts acessam os equipamentos usando a chave da sessão ...
python scripts/engine/vault/cli.py lock        # tranca ao terminar

# Modo terminal-puro (trava ao fechar o terminal; não compartilha com a IA)
eval "$(python scripts/engine/vault/cli.py unlock --env)"
```
