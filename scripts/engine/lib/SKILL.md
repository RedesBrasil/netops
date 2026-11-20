# SKILL — Inventory and identity migration

The `inventory.py` core resolves inheritance and selects hosts without changing the files.
`host_identity.py` keeps positive integer IDs up to `2^53 - 1`, a counter and reserved legacy
aliases. IDs are not editable. `load_inventory(include_credentials=False)`
reads metadata only; only the access transports need credentials.

## Automatic conversion in the console

From version 2 on, updating or starting the console in write mode through
`scripts/engine/ui/start.sh` recovers and converts legacy inventories automatically.
The console waits for it to finish before enabling its operations. There is no migration via GET,
no access to equipment and no reading of `credentials.yaml`; `--read-only` does not convert data.

During an update, the candidate pre-validates the documents without writing. Invalid
references prevent it from starting and the previous supervisor restores the code. The private
diagnostic is in `.netops-update/host-migration-preflight.json`. If the pre-validation passes,
the conversion waits for the supervisor to commit the code, for the new server's PID to be published
and for the recovery marker to be removed. Only then does it run `apply` with the expected hashes.

`/api/config/meta` reports `host_migration.phase`, `detail` and `blocking`. The blocking phases
are `waiting_for_commit`, `running` and `failed`; the API and WebSockets never see partially
converted data. `completed`, `not_required` and `read_only` end this step without a blocker of their own.
A failure after the commit keeps the new code, with a visible error and writes blocked; a normal
restart recovers the interrupted transaction and tries again. Conflicts or corrupted baselines
stay blocked, with no forced overwrite. See also `scripts/engine/update/SKILL.md`.

## Manual check and migration

Run from the installation root; there is no network access and no reading of the vault:

```bash
.venv/bin/python scripts/engine/lib/host_id_migration.py dry-run
.venv/bin/python scripts/engine/lib/host_id_migration.py apply
.venv/bin/python scripts/engine/lib/host_id_migration.py recover
.venv/bin/python scripts/engine/lib/host_id_migration.py rollback
```

`--root /caminho/instalacao` points to another installation. The dry-run writes no files.
Missing references block the migration and are listed by file/field; no
link is deleted and no equipment is invented. YAML comments and link IDs
are preserved; old names become aliases and old backup folders are associated
explicitly. New collections use `backups/by-id/<integer>/`.

Before the commit, the tool stores the baseline, prepared documents and hashes in
`runs/<date>-host-id-migration-<id>/`. The private journal in
`network/.host-id-migration.json` allows recovering from interruptions. `recover` automatically
restores an incomplete apply; `rollback` also undoes a completed
apply, as long as none of the four files was edited afterwards. The baselines
are kept. New collections in `backups/by-id/` also prevent a full rollback,
because reusing the identity could associate the history with another device.
Rollback never silently overwrites later edits.

The console and the migrator use the same `flock` per inventory directory. External tools
that edit YAML directly must be stopped during the migration. If a run
is left incomplete, recover before allowing new writes. To tie an apply to
a specific dry-run, save the returned JSON and pass `apply --expected-plan plano.json`.
