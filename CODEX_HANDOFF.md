# Current handoff

Reviewed November 24, 2026 on `codex/gift-mode`, PR #36. This index describes
source evidence; check runtime and device reports before operations.

## Current implementation

Gift mode adds editable welcome text, an immutable weather-neutral first picture,
two-asset integrity validation, firmware-capability gating and authenticated
ready/opened reports. Welcome persists across ordinary wakes and power cycles.
Only the right white button reveals the locally preloaded first picture.
Cancellation requires a matching device acknowledgement before a new gift.
No production gift has been armed as part of development.

The release pin and four-file recovery bundle target firmware v0.8.13, source
`3b5612f0bac2819780acbb9f8b8bb45cadf072f7`, official build
[45502035920](https://github.com/lstepnio/Emviary-firmware/actions/runs/45502035920).
263 host checks and the official ESP-IDF build passed. Actual backend assets
also passed the firmware manifest, SHA256, native gzip/palette and local-reveal
host fixture. This does not establish physical panel or offline qualification.

Service gift/owner/security/history/recovery/backup checks passed. Desktop and
390 px mobile previews showed complete artwork and readable messages. A bounded
status watcher updates readiness without waking the frame. The full CI suite
passed 514 tests before the final release metadata and documentation refresh;
check PR and main checks for final publication evidence.

## Operational evidence and remaining gates

Before this rollout, production was battery-feature source `be8bb4c`, GHCR digest
`sha256:79a48aa99ec98e30b9fda9b563a6cc1e1d5aad0caf9d71b5f397c0e7d341506d`.
The verified rollback backup is
`/downloads2/backups/rollouts/releases/emviary/20261124T221958.070972Z`.
The last inspected device reported v0.8.10 with stable-only automatic updates,
seven-day delay and no pin. Preserve that policy; published prereleases are not
proof of installation. Gift mode cannot arm until capability is reported.

A previously failed independent off-host backup attempt at 14:09 UTC is separate
from this feature. The verified rollout backup is available; do not describe
overall backup readiness as healthy without rechecking the independent job.

Still required: final source CI, container publication and rollout verification;
then policy-authorized firmware installation, actual welcome inspection, right
button reveal without Wi-Fi, power-cycle retention and cancellation acceptance.
No physical result should be inferred from rendered previews or HTTP delivery.

## Documentation

See [documentation review](docs/DOCUMENTATION_REVIEW_2026_11_24.md) for the complete
Markdown inventory, current guidance and historical-report dispositions. Preserve
canonical unrelated work and the separately versioned firmware history.
