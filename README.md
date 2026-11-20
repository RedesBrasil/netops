🇺🇸 English · 🇧🇷 [Português](README.pt-BR.md)

# NetOps

**Multi-agent framework for network and infrastructure operations.**

## One-line install (Linux)

Copy, paste into the terminal and you are done:

```bash
# already logged in as root:
curl -fsSL https://raw.githubusercontent.com/RedesBrasil/netops/main/install.sh | bash
# with an administrative account and sudo:
curl -fsSL https://raw.githubusercontent.com/RedesBrasil/netops/main/install.sh | sudo bash
```

The installer ([`install.sh`](install.sh)) does everything on its own. Root only **prepares the system**: packages
(Python, nmap, cron, ping, traceroute, mtr, ssh, git, gh, sudo), the `netops` service account (HOME
`/var/lib/netops`, no sudo) and the service. Then it downloads the latest release, checks the SHA256 and extracts it to
`/opt/netops`. The `.venv` and the `claude` agent are created **as `netops`**. **It asks no questions:**
it registers the systemd user service `netops-console@opt-netops` (starts at boot, no login needed), starts the
console listening on **all of the machine's IPs** (`0.0.0.0`, and `::` if IPv6 is available; the configuration stores
only the wildcard, never the list), tests everything and shows the **first-access link** for each IP
(`http://IP:port/#setup?token=...`, valid for 24 h).

**First access:** in the browser you choose the language (English/Português) and create the admin (name, e-mail,
password and confirmation). This password is the login and also the vault master password. When you finish, a one-time
root step (`/usr/local/sbin/netops-setup-finish`) enables `sudo` through the vault and generates the password of the
Local host, without you typing anything. Until then, the console only shows the wizard, which requires the link with the
token. Lost the link? `sudo -u netops python3 /opt/netops/scripts/engine/users/cli.py setup-link`.
Automated install: `NETOPS_MASTER_PASSWORD=... NETOPS_LANG=en|pt-BR` creates the vault during the install.
Server with a public IP: turn on **Settings → Web access** right after the first access.

**NetOps never runs as root:** console, AI, subagents, web terminal, scheduled tasks and
updates use the `netops` account. To administer **this** server as root (e.g. "install
Docker here"), the installer registers the **Local** host (`NETOPS-LOCAL`, protected) and the elevation account
`netops-admin`, whose random password is kept only in the vault: with the vault unlocked, the operation runs as
root without SSH and without you typing a password (see [`scripts/engine/localadmin/SKILL.md`](scripts/engine/localadmin/SKILL.md)).
Files as root: menu **Files → 🔓 Open as root**.

Requires systemd (VM or CT/LXC with systemd). Tested on Ubuntu 24.04 (LXC CT); Debian 12+, RHEL/Rocky/Alma 9+,
Fedora, openSUSE Tumbleweed and Arch are still supported by the installer, but the dedicated account has not yet been
validated on them in this version.
Running it again is safe: on an existing install it only checks and repairs, without touching code or
data. An **old install** (console as root) is not migrated automatically: the installer warns you and the
migration is a separate command, with dry-run and rollback
([`scripts/engine/identity/SKILL.md`](scripts/engine/identity/SKILL.md)).

Options (`sudo VAR=value bash` at the end of the pipe): `NETOPS_DIR`, `NETOPS_PORT`, `NETOPS_HOST`,
`NETOPS_VERSION`, `NETOPS_NO_LOCALADMIN=1` (does not create the Local host/`netops-admin`).

### Private repository: install with an SSH key (deploy key)

The official repository is public and uses the line above. This section is for those who keep a **private** copy of
NetOps: create your own **deploy key**, read-only and registered only in your repository. Whoever has it can
clone, but cannot write or see other repositories. **Never publish the private key** (README, issue, commit
or chat): generate yours with the steps below and keep it only on the server.

**1. Once per server**: prepares the server, generates the key and shows the public part:

```bash
sudo bash <<'EOF'
command -v git >/dev/null && command -v ssh-keygen >/dev/null && command -v curl >/dev/null && command -v python3 >/dev/null || {
  apt-get update -q && apt-get install -y -q git openssh-client curl python3 ca-certificates \
  || dnf install -y git openssh-clients curl python3 ca-certificates \
  || zypper -n install git openssh-clients curl python3 \
  || pacman -Sy --noconfirm git openssh curl python; }
install -d -m 700 /root/.ssh
[ -f /root/.ssh/netops_deploy ] || ssh-keygen -q -t ed25519 -N "" -C "netops-deploy-$(hostname)" -f /root/.ssh/netops_deploy
curl -fsSL https://api.github.com/meta | python3 -c 'import json,sys; [print("github.com", k) for k in json.load(sys.stdin)["ssh_keys"]]' > /root/.ssh/netops_known_hosts
printf '\nCopy the line below and add it in GitHub > RedesBrasil/netops > Settings > Deploy keys > Add deploy key (leave "Allow write access" UNCHECKED):\n\n'
cat /root/.ssh/netops_deploy.pub
EOF
```

**2. The install line** (after adding the key; it also works for the next server with the same key):

```bash
sudo bash -c 'D=$(mktemp -d) && GIT_SSH_COMMAND="ssh -i /root/.ssh/netops_deploy -o IdentitiesOnly=yes -o UserKnownHostsFile=/root/.ssh/netops_known_hosts -o StrictHostKeyChecking=yes" git clone -q --depth 1 git@github.com:RedesBrasil/netops.git $D/n && NETOPS_SSH_KEY=/root/.ssh/netops_deploy bash $D/n/install.sh; rm -rf $D'
```

The installer clones the latest release tag with the key and builds the same verified release package (use `NETOPS_VERSION=X.Y.Z`
for another version). The console update button uses `gh`: authenticate it on the server with `gh auth login`.

Open this folder in Claude Code, Codex, Cursor or Antigravity and ask, in plain language, for network
tasks — AI agents carry them out end to end: they read the inventory, connect to the
devices (SSH/Telnet/API), collect data, look up the internal documentation, apply
changes, test and write reports.

```
"Run a security assessment of my network."
"Configure OSPF on the MikroTik rt-core-01."
"Generate up-to-date documentation of the network."
```

## Getting started

1. **Install** with the line at the top. Manual install, without the installer:
   ```bash
   python3 -m venv .venv
   . .venv/bin/activate
   pip install -r requirements.txt
   sudo apt install nmap python-is-python3
   ```
   That's it: after this, no request needs to prepare an environment. Every script re-runs itself
   inside the `.venv` (`python3 scripts/...` is enough, no `activate`), and device access is
   always `python3 scripts/tools/access/session.py run --host-id <ID> --command "..."`.
2. **Register your devices** in `network/hosts.yaml` (copy from
   `network/hosts.example.yaml`). This file is git-ignored.
3. **Register the credentials** in `network/credentials.yaml` (copy from
   `network/credentials.example.yaml`). This file is git-ignored.
4. **(Recommended) Encrypt the passwords** with a master password:
   ```bash
   python3 scripts/engine/vault/cli.py init       # sets the master password
   python3 scripts/engine/vault/cli.py encrypt     # passwords -> "enc.v1:..."
   python3 scripts/engine/vault/cli.py unlock      # unlocks the session (at the start of work)
   ```
   The values stay encrypted at rest and are decrypted only in memory, during
   the session. See `scripts/engine/vault/SKILL.md`.
5. **Describe the topology** in `network/topology.yaml` (copy from
   `network/topology.example.yaml`). This file and the generated `topology.md` are git-ignored.
6. **Open the framework in your AI IDE and ask for what you need.**

Hosts use integer IDs generated by the console, permanent and separate from the hostname.
Scripts accept `--host-id 1`; `--host <hostname-or-alias>` is still available for
unique names and older automations. When you edit the name, the ID and its links are kept.
Old inventories are converted automatically when you update or start version 2
in write mode, with pre-validation, baseline and recovery. Invalid references
block the conversion without deleting links or inventing hosts. To check the data
beforehand or recover from an interruption, see `scripts/engine/lib/SKILL.md`.

## Network maps in the console

```bash
scripts/engine/ui/start.sh
```

Open **Maps** to draw the network on a computer or a phone. The inventory is the same as
**Hosts**: adding on either page shows up on the other. The general map includes all
devices; per-location maps use the Site field. You can create additional maps,
references between maps, multiple links, 90-degree bends, text and shapes.
Actions are on the right-click menu of the map, device or link, with the **⋯** alternative on phones.

The layout is saved on the server in `network/maps.yaml`, without duplicating hosts or passwords.
Links and optional interfaces remain in `network/topology.yaml`, edited through the
**Maps** page. The old Topology page was removed. Mermaid generation by script is still
available. See `scripts/engine/ui/SKILL.md`.

## One-click updates

In the console top bar, use **Check for updates**. The panel shows the installed version
 and the changelog of each later stable release. After saving forms and finishing active
work, choose **Update to vX.Y.Z** and confirm the backup and the update.

The launcher `scripts/engine/ui/start.sh` manages applying the update, the restart and recovery on failure.
To adopt this launcher for the first time, restart the console manually. After that, the flow is through the UI.
The repository is private: the GitHub CLI must be authenticated for the same user/HOME as the server
(`gh auth login --hostname github.com`). Applying an update requires a console login and does not work in read-only mode.

Packages do not replace local data with the distribution's examples. Inventory, credentials,
maps, memory, local configuration, backups, reports, runs and customizations are preserved;
version 2 converts only the identity formats and references that need it. The updater
checks a private snapshot before applying and tries to restore the previous code if the new version
does not start. Data conversion only starts after the launcher confirms the code.
If that later step fails, the new code stays and the interface blocks operations with
recovery guidance. Locally modified engine code blocks automatic application.
Also keep an external backup against disk failures.

Details and recovery: `scripts/engine/update/SKILL.md`. To publish versions, agents must
follow `core/rules/releases.md`: check the latest release, bump the version and generate the changelog.
The manual **NetOps release** workflow validates tests/package before publishing; this implementation
does not publish or update installs automatically without the operator's action.

## Structure

| Folder | What it contains |
|-------|--------------|
| `agents/` | The 5 AI agents (coordinator, planner, executor, tester, documenter) |
| `best-practices/` | Best practices as text, per vendor and general |
| `config-examples/` | Real configuration examples, per vendor |
| `scripts/` | Access scripts (SSH/Telnet/API) and diagnostics (ports, ping, tracert) |
| `planning-examples/` | Planning template documents |
| `network/` | Inventory: hosts, credentials, topology and backup service config (`backups.yaml`) |
| `workflows/` | Pipelines that orchestrate the agents |
| `memory/` | Memory and self-learning — the "living project" |
| `runs/` · `reports/` | Raw run output · final reports |
| `backups/` | Device configuration backups, one file per host (console **Backups** tab) |
| `core/` | Framework config, schemas, templates and rules |

## Principles

It is a **living project**: every run records what it learned in `memory/`, and that
knowledge improves the documentation for the next ones. Everything is **standardized** (see
`core/rules/standard.md`) and follows `constitution.md`.

## Origin

Built from patterns of three reference frameworks:
[AIOX](https://github.com/SynkraAI/aiox-core) (agent authority, handoff, workflows,
multi-IDE), [OpenSquad](https://github.com/renatoasse/opensquad) (file-based structure,
agent/skill format, best-practices catalog) and
[Hermes](https://github.com/nousresearch/hermes-agent) (memory and self-learning).
