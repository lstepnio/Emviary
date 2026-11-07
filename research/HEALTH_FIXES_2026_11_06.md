# Health findings remediation, November 6, 2026

## Scope and current outcome

Authorized: recheck and fix the health findings, starting with backup scheduling
and updater reliability, then test and deploy while preserving unrelated work.
Production now runs application 0.19.1, image `emviary:poc-071`, application
source `c4dec68c2f5de2f16f9992ccb5f198995bf18c71`. Firmware and artwork were not deployed.

The previous report was stale in two consequential ways: the host updater's
latest scheduled run had succeeded, but Emviary's backup directory was empty,
root-owned and unwritable by the application. The last independent success was
November 1 and the Mac's latest pull had failed. Those failures are now visible
through freshness and latest-attempt checks instead of a permanent success label.

## Changes and evidence

- Shared cold backup moved from 04:15 to 05:15 Denver time; updates from 04:45
  to 05:45. This preserves half-hour backup reuse after the frame's 04:15 wake.
  The missed-start watchdog uses matching times and a new activation window.
- Updater discards an unavailable staged image and defers only that service,
  without weakening its one-day observation delay. Other Docker failures still
  fail closed. The original October 28 missing image is consistent with this
  path; its original pruning event cannot be reconstructed from current state.
- Applied only the host patch, not unrelated local image-cleanup work.
  Infrastructure tests: 119 checks including staged image/daemon failures;
  14 updater tests additionally exercised the exact deployed source.
- Corrected only the empty Emviary backup directory to uid/gid 1000, mode 0700.
  No data or backup was deleted. Fresh local backup `pre-health-20261106` passed
  isolated restore verification, then the Mac download independently passed its
  own rehearsal (1,507 files, 561 retained images, 181 artworks).
- Local/off-host backup evidence expires after 36 hours. Unwritable destinations,
  missing records, invalid/future timestamps and newer failed pulls are explicit.
- Missing scheduled preparation is detected after a five-minute grace period;
  unresolved old failures no longer vanish merely because two days passed.
- Owner-authenticated `/manage/readiness` and `emviary readiness` share the same
  evidence. Live HTTP 200, CLI exit 0, status ready, both backups fresh, no frame alerts.
- Independent host monitor runs every 15 minutes, retries transient CLI failures,
  repeats unresolved alerts daily and reports recovery. Failure/deduplication,
  malformed state and publisher failures were tested with a simulated publisher.
  Its first real systemd execution succeeded. No live fault notification was
  deliberately injected; notification acceptance does not prove human receipt.
- Existing frame policy explicitly changed from all/zero-delay to stable/seven-day.
  No immediate firmware command or wake was requested.
- Deployed the reviewed recipient guide and clearer history/default-policy docs.
  Past compositions remain backed by device reports; prepared/delivered output
  alone does not establish display.

## Verification and preservation

Backend suite: 433 passed. Additional focused checks cover the final permission
and monitor changes. Ruff lint/format and diff checks passed. The backend's
Starlette/httpx deprecation warning remains unrelated to these changes.

Selective application deployment compared container identities and start times:
only Emviary changed. SQLite quick_check passed and foreign_key_check returned
zero violations. Live overview, recovery, appearance, events, battery, settings
and guide routes returned 200. Hidden-browser checks navigated those pages and
decoded visible images with no page JavaScript errors. The overview measured
390 px wide at a 390 px viewport. No settings or recovery actions were submitted.
Liveness remains independent of readiness. No image-delivery endpoint was called.

## Schedule-change incident

Reloading/restarting the calendar timers unexpectedly triggered the cold backup
immediately. It stopped 18 applications at 22:56:23 MST and restored them healthy
by 22:58:59 MST, November 6. The same container IDs were retained. The running
cold snapshot was allowed to restore applications safely rather than interrupted.
All applications were running and healthy after restoration. This was an
avoidable interruption caused by this task, not a claim of zero downtime.
The queued update began when backup finished. It was stopped during image export,
before any further application stops or replacements; no restart journal remained.
Its existing failure notifier accepted a cancellation notification. The failed-unit
flag was reset only after a successful explicit observation-only updater pass.
That pass checked all eligible registry references and one mature candidate,
without changing any container identity, start time or deployment pin.
The host backup ultimately passed full archive verification at 23:10:28 MST,
November 6, with 12,618,125,536 archive bytes and 156.7 seconds stop/recovery.

Future schedule changes must stop timers before editing/reloading calendars,
review elapsed events and queued jobs, and verify a future-only first trigger;
restarting a calendar timer is not a schedule-only guarantee.
The deployment itself later changed only Emviary.

## Rollback and remaining boundaries

Private host originals and before-state evidence:
`/var/lib/one-maintenance-recovery/20261107T055510Z`.
Private application originals:
`/docker/backups/emviary-deployments/health-20261106`.
Restore only affected files or the Emviary image entry after reviewing newer
changes; do not overwrite newer unrelated pins. Pre-deployment verified snapshots
contain the old frame policy and compatible data. Disable only emviary-watch.timer
to roll back the independent monitor. Preserve all existing recovery material.

Backup deletion remains manual: keep manual/pinned recovery points and at least
35 daily verified copies pending a deliberate retention action. No automatic
backup deletion was enabled. Weather source normalization was retained; the
previous minor cloud-code disagreement did not establish a provider outage.

This task proves server readiness, backup restoration and browser/code behavior.
It does not optically verify the frame, test destination Wi-Fi, or establish a
battery lifetime. The next overnight frame report remains separate acceptance.
