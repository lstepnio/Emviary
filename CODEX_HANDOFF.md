# Current handoff

Updated November 24, 2026 after [PR #36](https://github.com/lstepnio/Emviary/pull/36)
and the verified production rollout. Recheck runtime and device reports before operations.

## Ready to wrap implementation, November 24

The current source adds owner confirmation of the actual welcome, a final Ready
to wrap command and authenticated device acknowledgment. Only a durably wrapped
gift reveals its immutable first picture on genuine power-on, before Wi-Fi;
software resets and timer/green wakes preserve the welcome. Right white is a
manual fallback. Revised welcome removes button instructions, balances text and
adds a small red heart. Preparing/loading does not arm automatic opening.

Firmware v0.8.15 source `2d81bd42bc2805a94b47d36e66d6603884b9e869` passed all263
host tests and official ESP-IDF6 build45516796393. The recovery files are hash-
verified and pinned together. A fixture using actual converted assets, real
SHA256 and native validation passed wrapped persistence and offline boot reveal.
112 targeted service checks passed. Desktop/390px previews showed no overflow,
clipped controls or broken gift images. Final PR/main/container gates precede
rollout; record runtime evidence separately.

The prior running frame was authenticated on v0.8.13 at23:45 UTC November24.
Its owner-requested policy is automatic stable updates, zero-day delay, no pin.
Preserve the zero-day preference after any exact-version installation exception.
The fresh verified rollback capture is
`/downloads2/backups/rollouts/releases/emviary/20261125T000738.324787Z`, from
GHCR digest65fba36e5d5dcf26b8873eeb2b8d4564d7f90dee8a7b25e963379a400243317d.
No physical wrap/offline power-cycle result is inferred from the host fixture.
Earlier source/deployment observations below are dated history.

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
status watcher updates readiness without waking the frame. The final PR and main checks passed all 514 service tests, Ruff checks and browser
recovery checks. [Main checks](https://github.com/lstepnio/Emviary/actions/runs/45505461132)
gated [container publication](https://github.com/lstepnio/Emviary/actions/runs/45506481665).

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

Production now runs source `17214900d5ec602f39e2112a94ea7f66aadd8fda`, image
`ghcr.io/lstepnio/emviary@sha256:65fba36e5d5dcf26b8873eeb2b8d4564d7f90dee8a7b25e963379a400243317d`.
Only Emviary was recreated; environment, mounts and unrelated container IDs were
preserved. Health, gallery, v0.8.13 recovery manifest and gift imports passed.
Cookie-free home-network access to Appearance returned the authenticated gift
controls; an unauthenticated gift request returned 401. Live desktop and 390 px
mobile controls had no horizontal overflow or clipped inputs.

Post-rollout read-only inspection confirmed v0.8.10, 92%, automatic stable-only
updates, seven-day delay, no pin and zero production gift packages. Local backup
is fresh and frame alerts are empty. Overall readiness still flags the independent
backup failure recorded at 14:09 UTC; this rollout did not repair that job.

Still required: policy-authorized firmware installation, actual welcome inspection,
right-button reveal without Wi-Fi, power-cycle retention and cancellation acceptance.
No physical result should be inferred from rendered previews or HTTP delivery.

## Documentation

See [documentation review](docs/DOCUMENTATION_REVIEW_2026_11_24.md) for the complete
Markdown inventory, current guidance and historical-report dispositions. Preserve
canonical unrelated work and the separately versioned firmware history.
