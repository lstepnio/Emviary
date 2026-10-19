# Recovery and management status resilience

Reviewed October 19, 2026, America/Denver.

## Confirmed production failure

`/manage/recovery?frame=emily-e1002` returned HTTP 500 because backup discovery
called `is_file()` on `/backups/composition-release-20261016/COMPLETE` outside
its exception handler. That root-only folder held deployment rollback metadata
from the earlier composition-planning deployment, not an application backup.

Move the unchanged rollback folder to
`/docker/backups/emviary-deployments/composition-release-20261016`. Retain its
private permissions. Recovery and the other management pages then return 200.
Future deployment snapshots belong outside the application backup directory.

## Permanent fixes and adjacent review

- Isolate every backup filesystem operation, including directory listing and
  marker stat/read operations. An inaccessible directory cannot break recovery.
- Validate optional status records as JSON objects with timezone-aware timestamps.
  Compare actual instants when choosing the newest verified backup. Ignore links.
- Distinguish unavailable status from no verified backup, and show partial-read
  warnings while retaining other valid results. Do not expose filesystem paths.
- Treat malformed independent-copy metadata as unavailable. Reading status does
  not run a backup, alter evidence, or claim a fresh restore verification.
- Revalidate optional stored device readings before health, saved-network, or USB
  status rendering. Ignore invalid readings without changing stored evidence.
  USB confirmation can use only valid evidence, never a fabricated successful state.
- Handle malformed optional forecast/job timestamps in management alerts, and
  invalid battery timestamps, flags, and voltage in advisory displays.
- Format unavailable timestamps consistently instead of raising an exception.
- Render recovery controls for one selected frame, preserving unique USB control
  IDs. Keep the empty-frame page's details elements balanced.
- Return controlled 404/503 responses for unknown frame status, unavailable USB
  files, and malformed verified-bundle metadata. Authentication and immutable
  firmware verification remain required. No device flashing or recovery write is
  performed as part of this repair.

## Verification

Regression tests cover the original PermissionError even when tests run with
filesystem privileges, malformed status JSON and timestamps, inaccessible backup
roots, chronological ordering across timezone offsets, symlink avoidance, bad
historical readings, multi-frame and empty recovery pages, and controlled USB
errors. Existing recovery and management suites remain part of release validation.

Live checks cover recovery, overview, appearance, events, settings, battery,
artwork, and event-art pages. Validate the deployed recovery page in the browser,
verify backup restore rehearsal independently, and preserve frame credentials,
policy, firmware, and unrelated containers during deployment.
