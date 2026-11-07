# Emviary health check, October 28, 2026

Observed at 2026-10-28T19:37-06:00. Read-only operational inspection against source main
`98d8a2455b33d74dcdfb557dc6e3dda6c3aaafa4`. No deployment, firmware operation,
live policy change, container restart or maintenance rescheduling was performed.
This report and the handoff note are local documentation changes only.

## Assessment

The service, cached artwork and recent frame reports are healthy. There is no
observed current application outage. The most concrete reliability risk is a
shared-host cold backup scheduled at exactly the frame's daily wake. The host
updater also failed today. Current successful frame requests do not remove
those risks.

## Healthy evidence

| Area | Current evidence | Limit |
|---|---|---|
| Application | Production 0.19.0, `emviary:poc-070`, application commit `0918cfd1084a9effac5a3483b1d4210b4b4f538e`; Docker healthy, zero health failures and no OOM kill | This is the October 23 build, not latest main |
| Logs | Last 48 hours: no application tracebacks, warnings or logged HTTP 5xx in the inspected container log | A stopped service cannot log failed incoming requests; this does not establish zero downtime |
| Resources | Container about 143 MiB of 512 MiB; host about 10.9 GiB available RAM; root disk 23% used with 168 GiB available; shared backup volume about 1.9 TiB free | Point-in-time resource observations |
| Database | SQLite quick_check OK, no foreign-key violations; about 27 MB | Not a stress or corruption-injection test |
| Frame | Last check-in October 28 at 04:15 MDT; v0.8.10; 96%, 4.078 V, USB/charging false; latest RSSI -57 dBm | Readings are about 15 hours old, normal for the daily sleeping schedule |
| Overnight reports | Twelve consecutive daily check-ins, October 17 through 28, reporting prior refresh success, HTTP 200 and one attempt; roughly 33-35 second prior refreshes | Device reports describe earlier operations and are not independent optical proof |
| Artwork | Last reported image 416, last sent image 430 and navigation image 438 passed compressed-artwork hash/packed-pixel validation; previews 800x480 | Today's sent picture remains unconfirmed until a later device report |
| Next refresh | October 29 planned composition preview exists at 800x480; no slot errors or pending refills; latest rendering jobs completed | Preview preparation is distinct from delivery and display |
| Weather | Open-Meteo and NWS both refreshed at 19:32 MDT; render completed at 19:32:18; NWS selected when cloud-cover codes differed | Current disagreement is not an outage: sampled highs/lows were close, cloud-cover codes differed |
| Backups | October 28 server backup records a passed restore rehearsal; Mac copy verified at 06:31 MDT, LaunchAgent loaded with exit 0 | This check inspected today's completion evidence, not another full restore rehearsal |
| Web | Overview, appearance, events, battery, settings, recovery and homepage returned 200 in a real hidden browser; visible images decoded, no page JavaScript errors; overview fits 390 px | Actions such as recovery, saving settings and advancing the frame were deliberately not invoked |
| TLS | HTTPS validated; Let's Encrypt certificate expires January 6, 2027 | Current validity does not prove future renewal |

The twelve successful nights are useful live operating evidence. They should
count toward qualification where the operating profile matches the gift.
Destination connectivity, direct panel acceptance, recovery and a controlled
battery discharge remain separate checks. Do not infer a charging interval
from a nearly flat percentage reading.

## Prioritized improvements

### 1. P1: Move cold backup outside the frame's wake/preparation window

`one-docker-backup.timer` is explicitly scheduled for 04:15 America/Denver,
the same time as the frame. `/docker/ops/server_ops.py` backup lines 258-275
stops the running Compose applications for a cold snapshot, then resumes them.

Container lifecycle evidence:

- October 27: Emviary stopped about 04:16:15 and started about 04:18:07 MDT.
- October 28: Emviary stopped about 04:15:26 and completed startup about 04:17:54 MDT.
- The October 28 shared backup completed successfully at 04:32 MDT; only part
  of that period was application downtime.

Today's artwork request arrived before shutdown. A slower Wi-Fi association,
retry or later firmware-metadata request can fall into this avoidable outage.
Reschedule the shared backup away from 03:30 preparation and 04:15 wake, after
reviewing other shared-service requirements. Longer term, consider using the
verified application backup in the host archive instead of stopping Emviary,
but do not exclude its live data without a consistent replacement.

### 2. P1: Repair the failed host updater

`one-docker-update.service` failed on October 28 at 04:45 MDT, exit 1, with
Docker reporting a missing SHA256 image reference. The later update plan did
not complete. Emviary was explicitly held as a local/manual release and is
healthy. Caddy and Netdata also report healthy; Dozzle is running.

The host accepted an ntfy notification for the failure. That is notification
acceptance, not confirmation that a person received it. Investigate the staged
image/rollback reference and resume only after verifying current running images.
No running container or current exact-image override matched the missing image
in the inspected records; its precise provenance remains unresolved.

### 3. P1: Deliberately choose the existing frame's update policy

The saved frame policy remains automatic, all releases and zero-day delay,
without a version pin. Main's stable/seven-day defaults apply to new policies;
they do not overwrite explicitly stored preferences. Deployment alone will not
put this frame on the conservative policy.

For a maintainer-operated gift, pin a physically tested version or explicitly
choose stable/delayed updates after reviewing the desired rollout behavior.
The policy was inspected but not changed in this task.

### 4. P2: Add operational readiness and deadline-based alerts

`/healthz` checks SQLite with SELECT 1. Keep that liveness probe, but add an
authenticated readiness summary and an independent monitor for scheduled frame
contact, overdue preparation, and local/off-host backup freshness.

Concrete source gaps found in `src/emviary/backup_status.py` and
`src/emviary/diagnostics.py`:

- Old backup-success timestamps have no stale threshold in the backup card.
- Off-host pull failure leaves the server's previous success receipt untouched.
- Preparation warnings depend on recent failed records. An absent job or an
  unresolved failure older than two days can lose the preparation warning.
- Most application warnings require opening the management page; the host
  updater's notification path is separate from frame/readiness monitoring.

Use expected schedules and last-attempt outcomes rather than page visits or
HTTP 200 alone. This is a monitoring gap, not evidence of a missed backup today.

### 5. P2: Plan the next application deployment explicitly

Main includes PR #10's recipient guide, safer new-frame defaults and clarified
support text; production still runs `0918cfd`. `/guide` returns 404 as expected
on that older build. Schedule a selective application deployment with the
normal backup/rollback checks, separately from choosing the frame update policy.
Do not treat a GitHub merge as a deployment.

### 6. P2: Bound independent-backup growth

The Mac backup directory uses about 8.8 GiB; the latest full server backup is
about 506 MiB. The Mac has about 114 GiB free. The pull tool intentionally has
no automatic retention, so continued full daily copies warrant a reviewed
retention policy. Preserve verified recovery points and manual/pinned snapshots;
no backups were deleted during this check.

### 7. P3: Clarify documentation and weather-source messaging

RUNBOOK lines 397-403 still describe past compositions as prepared history,
although display reports now drive past cards. Its historical application-0.11
section also retains all/zero-delay wording alongside current safer defaults.
Clarify historical versus current behavior and explicitly persisted preferences.

Weather disagreement messaging could distinguish small cloud-cover differences
from materially different temperature forecasts. Both sources are functioning;
this is a clarity improvement, not a reason to replace the fallback algorithm.

## Recommended sequence and confidence

First remove the maintenance/wake collision and repair the host updater. Then
review the frame's persisted update policy, stage the already-reviewed application
release, and add deadline-based readiness monitoring. Follow with backup retention
and documentation cleanup.

The strongest counterargument to calling this fully healthy is that liveness,
clean logs and successful prior device reports do not prove availability during
the cold-backup gap or the current physical panel. Confidence is high in the
observed server/data state and in the scheduling conflict, moderate in broader
readiness until the monitoring gaps and physical acceptance are addressed.
