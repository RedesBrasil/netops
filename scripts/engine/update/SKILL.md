# NetOps updates

## Usage

Always start through `scripts/engine/ui/start.sh`. In the top bar, click **Check for updates** (Verificar atualizações), read the notes of all later versions and choose **Update to vX.Y.Z** (Atualizar para vX.Y.Z). Save forms before confirming. Open terminals and agent sessions do not block: they are closed on restart (Claude conversations stay saved and can be resumed). Only an equipment backup or a running workflow prevents the update until it finishes.

The official repository is `RedesBrasil/netops`, currently private. Install GitHub CLI and run `gh auth login --hostname github.com` as the same user and HOME as the server. Do not pass tokens through the interface. The updater uses `gh api`; it does not print or export credentials.

Applying requires login with the master password, even on installations where the rest of the console is open for lack of a vault. Read-only mode allows checking, but not applying. It is not necessary to unlock or decrypt the credentials to back up the installation.

## What is preserved

- Inventory, encrypted credentials, maps, topology, equipment backups, reports and runs;
  old identity formats are converted by the protocol described below, not replaced
  by examples from the package.
- Local project configuration, memory, unknown files, environments and personal histories.
- Customizations of agents, workflows, knowledge and operational scripts. Local edits and deletions are not replaced by distribution versions.
- `.git/` and the HOME outside the project are not changed. The updater does no checkout, reset, clean, pull or stash.

Locally modified engine code or new paths colliding with existing files prevent the automatic update. The initial reference of a legacy clone is the content of `HEAD`; afterwards, it is the private manifest `.netops-update/installed.json`. That is why, after installing a package, `git status` may show distribution changes: the updater does not use the working tree as the installation reference.

## Automatic migration of host IDs

Version 2 converts `hosts.yaml`, `topology.yaml` and `maps.yaml` to v2 and the backup
configuration to v3, keeping names, attributes, layouts, link IDs and history.
Old IDs become aliases; new collections use `backups/by-id/<id>/`. There is no access to
equipment nor reading of the vault in this conversion.

The candidate first runs a pre-validation without modifying the documents. Invalid data,
such as links to nonexistent hosts, prevents the new version from becoming ready: the previous
supervisor restores the code and the old data stays intact. The diagnosis is kept
private in `.netops-update/host-migration-preflight.json`. No link is discarded
automatically; the fix requires a decision by the operator.

With valid data, the candidate waits for the code confirmation and for the supervisor to publish its
identity. Only then does it convert the four documents under the inventory
lock, with expected hashes, its own baseline and journal. This keeps compatibility
with supervisors from earlier releases, which know how to restore code, but not how to undo
a data conversion. The package stays on protocol 1, with no post-install scripts.

Until it finishes, the interface shows the preparation and the APIs and WebSockets are blocked,
except the minimal status queries. `host_migration` in the metadata reports the phase and
whether there is a block. The public status uses `migrating` or `migration_failed` and does not announce the
update as completed while the data is blocked.

A normal start through the launcher also recovers/converts legacy inventories before
releasing the console. `--read-only` never performs this write. Already converted inventories
do not receive new IDs; installations without an inventory do not create equipment.

## Backup and limits

`.netops-update/` contains jobs, packages, snapshot and journal. New Python environments live in
`.netops-venvs/`, git-ignored, with no private data and accessible to the terminal's reduced user. It is private (`0700`, backups `0600`), git-ignored and not served by the API. Do not copy this directory into reports nor publish it. The `snapshot.json` file records original hashes and permissions, with no secret content.

The snapshot includes regular files of the installation and of an external DATA_ROOT, with links recorded without following their targets. Regenerable exclusions: `.git`, `.venv`, `.netops-venvs`, `node_modules`, `__pycache__`, `.pytest_cache` and the update directory itself. The previous Python environment is kept separately when it is replaced. External links and files outside these directories stay untouched, but are not covered by the snapshot.

Backups are not deleted automatically. Reserve space for the snapshot, the package and the new Python environment. Also keep a backup on another disk: no update can guarantee recovery from physical failure, storage corruption or concurrent changes by external processes. Pause editors, CLIs, cron and other external writers during the update. The console blocks its own writers and sessions, not every process on the system.

Packages are limited to 256 MiB compressed, 512 MiB uncompressed and 10 thousand files, with no links, special entries or execution of post-install scripts. The asset digest comes from the authenticated GitHub API and each file is checked against the manifest. Checksums do not replace trust in the repository maintainers. Releases without a compatible package, drafts, prereleases and downgrades are not applied.

## Recovery

The supervisor runs from a private copy of the updater. First it prepares the package, snapshot and dependencies while the console reports progress in maintenance mode. Then it stops only its own process, applies the code and starts the candidate version on the same port. It only confirms the installation after receiving an HTTP response with the correct version and startup identity.

A startup failure, including in the conversion pre-validation, restores the previous code and environment
automatically, before changing the identity data. The console login
may be requested again after the restart.

A failure during the conversion after confirmation keeps the new code and blocks the console
with **ID migration blocked**. The data transaction tries to restore its own baseline;
baseline and journal are preserved. There is no automatic rollback of the code at this stage.
A new start through the launcher recovers an interrupted apply and tries the conversion again.
Invalid references must be fixed after a `dry-run`; external edits or a corrupted baseline
require human comparison and are not overwritten to force the opening.
Procedures and commands: `scripts/engine/lib/SKILL.md`.

After an unexpected interruption, run `scripts/engine/ui/start.sh` again: unconfirmed journals are reverted before the console opens. If the previous process is still alive, the launcher refuses the recovery until the operator stops it; it does not kill processes by a reused PID. If the status is `recovery_failed`, the launcher refuses to start so as not to hide an incomplete recovery. Do not delete the journal nor the snapshot. With the processes stopped, an operator must check the files listed in `journal.json`, recover the originals from `jobs/<id>/backup/installation/` respecting the permissions in `snapshot.json`, and restore the `.venv` selection if necessary. Only after validating the whole installation may they close the incident manually. A conflict with a file changed externally requires human comparison, never a forced overwrite.

## Releases and tests

Before generating a version, follow `core/rules/releases.md`. The command `python3 scripts/engine/update/release.py --output /tmp/netops-release-NOVO` queries GitHub and prepares a package from `HEAD` without publishing. It requires a committed version and changelog.

Tests: `.venv/bin/python3 -m pytest scripts/engine/ui/tests/ -q`. Apply tests must use a **complete temporary copy of the code and fake data**. Only changing `NETOPS_UI_DATA_ROOT` does not isolate the engine that would be updated. Never test applying against the real console.
