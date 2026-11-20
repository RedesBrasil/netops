# Permanent rule: NetOps releases

Every agent must read this rule before preparing or publishing a release.

## Before choosing the version

1. Check the official GitHub: `gh release list --repo RedesBrasil/netops --limit 100` and, if there are releases, look at the latest stable one with `gh release view <tag> --repo RedesBrasil/netops`.
2. An authentication, connection or permission error does not mean there are no releases. Resolve the query before continuing. The repository may be private.
3. Compare the latest stable release with `metadata.version` in `core/config/core-config.yaml`. This is the only manual version of the product. The constitution version is independent.
4. Choose a SemVer `X.Y.Z` higher than the latest stable: PATCH for compatible fixes, MINOR for compatible features, MAJOR for incompatibilities. Never move or reuse a published tag.

## Preparation

- Review the commits and changes since the last published tag. On the first release, describe the initial set honestly.
- Update the central version and `CHANGELOG.md` with `## [X.Y.Z] - YYYY-MM-DD`, new features, fixes and compatibility/data-preservation notes. Do not include customer data, private IPs, credentials or personal history.
- Run the Python/JS tests and validate the extraction of the package in a temporary directory.
- Explicitly check the diff and the list of distributed files. The package includes only authorized paths and objects from `HEAD`; ignored files and local content must not get in through an indiscriminate disk scan.
- Frontend assets must be ready in the repository. The operator does not need npm to update.
- Do not publish a destructive data migration. Format changes need proven compatibility or a specific protocol with backup and rollback before they are accepted by the updater.

## Authorized publication

Implementing code does not automatically authorize a commit, push, tag creation or external publication. Confirm this stage when it was not explicitly requested.

After the code is approved, committed and integrated into `main`, manually run the **NetOps release** workflow in GitHub Actions, passing `X.Y.Z`. The workflow:

1. Checks the branch and version, runs the tests and queries the existing releases again.
2. Generates `netops-X.Y.Z.tar.gz` with manifest, hashes and permissions, plus `SHA256SUMS` and notes.
3. Creates a draft with the tag and the version changelog, without replacing an existing release.
4. Checks the digest returned by GitHub and only then publishes the stable release.

If it fails after creating the draft, keep it private and investigate. Do not automatically create another tag or publish a partial package to work around the failure. Releases without a verifiable package cannot be installed by the console.

The workflow can resume a draft of the **same revision**, replacing its private assets and
checking both digests again. A draft of another revision requires investigation and an explicit
adjustment of the target before the new run; a tag that has already been published is never moved.
The check uses `gh release view`, because `/releases/tags/<tag>` returns 404 for drafts
whose tag does not exist yet. A published release or unknown assets block the resume.

## Final validation

Query the published release, check the tag, changelog and assets. Check in the console the listing of all higher versions and run an update test on an isolated copy, comparing data before/after. Clearly report what was published, what was only prepared and which tests actually ran.
