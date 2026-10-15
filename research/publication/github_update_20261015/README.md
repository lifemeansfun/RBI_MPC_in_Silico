# GitHub preservation checkpoint

This package publishes the curated experimental upgrade and the separate original-main manuscript on `project_upgrade_codex`, following the user's 15 October 2026 request. Main remains the original baseline. Scientific status remains **research incomplete**.

- `file_manifest.json` records SHA-256 and size for the publication payload. It excludes this publication directory to avoid self-reference; Git identifies the complete resulting commit.
- `publication_audit.json` records inclusion/exclusion counts, oversized-file and credential-pattern checks, and a local-only archive summary. Pattern scanning is a scoped check, not proof that arbitrary secrets cannot exist.
- `verification/` contains new command/environment/results/log records for offline verification of an export of the Git index. Generated test checkouts are excluded. No existing scientific outputs are overwritten.

The preserved 10 October closeout and its 518-pass test record retain their original bytes and scope. New packaging checks have separate 15 October records. Existing bundle protocols retain their exact code/settings/input hashes. For a historical bundle, execute from its own `bundle/code/` directory with a compatible locked environment; adding or changing active source/scripts/Makefile can invalidate a historical freeze at the active root.

The new export passed 518 tests in 196.24 seconds, `pip check`, offline source reconstruction/saved mock-study verification, fixture creation/validation, and relocated replay from the historical bundle. The current environment was reused; this is not a fresh installation or a live scientific study. Only documentation and exclusion of duplicate scratch artifacts changed after the test export; the final payload check binds unchanged scientific/runtime inputs to that export.

The default offline reproduction requires the complete saved mock study under `results/upgrade_validation_round_001/root_oct08_20261008/full_mock_diagnostic_attempt_001/`; it is included with its anchors and raw evidence. It is mock/replay evidence, not independent live replication.

## Local records intentionally outside this GitHub package

Copied verification checkouts and test scratch trees, installed runtimes/caches, duplicate portable bundles/evidence, review agent event streams, large review/input ZIPs, unrelated coursework and new third-party article fulltexts remain local. Acquisition metadata, source hashes and method assessments remain included. No local files are deleted. Exclusion rules live in the root `.gitignore`; this package is not a full backup of the local archive.

Historical manifests, reports and raw logs are preserved rather than rewritten, including absolute paths and references to omitted local copies. Some historical links therefore require the local archive. The original-main manuscript's saved QA receipt covers its earlier revision; this checkpoint does not certify the current DOCX's page layout. See the root [status page](../../../PROJECT_STATUS.md) and [continuation plan](../../planning/github_update_20261015/PLAN.md).
