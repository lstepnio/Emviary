# Emviary continuation notes

## November 9 Colorado bird variants

The live 0.19.3 catalog now includes 14 new cutouts for seven species, with
three live illustrations per species and 183 bird illustrations total.
Previously removed art stays removed. Each new illustration passed solo and
three-bird Spectra 6 preview review. Seeded selection verified eligibility,
unchanged species weights and no duplicate species within a trio. All 39
focused tests passed, and all 14 live masters and thumbnails matched the
release checks. Service readiness and the host monitor reported ready.

Catalog SHA-256: `94dfdcc1f91cabd60f5cd4b11f7f7e59fdb9922a6011cc8f17052bc9e717a87a`.
Rollback catalog: `/docker/backups/emviary-deployments/colorado-bird-variants-20261109T215816Z/catalog.json`.
See [Colorado bird coverage](art/COLORADO-BIRD-COVERAGE.md) for collection gaps.
Physical display of the new art remains unconfirmed.

## November 9 completed wildlife variants and coat labels

Deployed 0.19.3 (`emviary:poc-073`, runtime source `6131511`). Six portraits
bring the collection to 70 illustrations across 23 rotation identities. All
22 wild species have three illustrations. Wally has four. The red, black and
cross red fox coats retain one *Vulpes vulpes* identity. The public library,
management gallery and new frame compositions display the coat phase for
red fox, Abert's squirrel and black bear.

All six new packed previews, the three red fox label previews and 76 focused
tests passed. Live artwork and changed source files match the tested files by
SHA-256. The Red Fox gallery at 390 px fits the viewport and expands to all
three labels. Owner readiness and the host monitor reported ready. No new
composition has physical display confirmation from this check.

The catalog SHA-256 is `ecba7ecbd920aba894483d6fbff07b3b439734756751d02a147e71a952a9b76a`.
The verified application backup is `pre-wildlife-coat-phases-20261109`.
Rollback files are under `/docker/backups/emviary-deployments/wildlife-coat-phases-20261109`.

## November 9 riparian and small mammal variants

Fourteen additional illustrations give the raccoon, beaver, both prairie dogs,
fox squirrel, Colorado chipmunk and golden-mantled ground squirrel three
portraits each. The live catalog has 64 mammal illustrations across 23 species
identities, all with multiple portraits. All 14 packed Spectra 6 previews and
58 focused tests passed. The live library returned seven groups of three and
all 14 new thumbnails decoded. Owner readiness and the host monitor reported
ready after the art-only reload on 0.19.2. Live catalog SHA-256 is
`561b578f5a431f3fa64541b356d5d2354ee496ccee437e92037c153b8d4a734a`.
The previous catalog is under `/docker/backups/emviary-deployments/colorado-seven-variants-20261109T204425Z`.
Physical display of these compositions remains unconfirmed.

## November 9 pronghorn, coyote, bobcat, pika and marmot variants

Ten new illustrations give these five animals three portraits each. Their
existing species identities and rotation schedule are preserved. All ten
packed Spectra 6 previews and 51 focused tests passed. The live 0.19.2 library
returned five groups of three, all ten thumbnails decoded, and owner and host
readiness reported ready. Live catalog SHA-256 is
`4bd744a12f62846b1dcbab02900950beaf622a80cd3edf183a638243fa97838c`.
The previous catalog is under `/docker/backups/emviary-deployments/colorado-five-variants-20261109T190830Z`.
Physical display of these compositions remains unconfirmed.

## November 9 seasonal wildlife variants

Eight additional illustrations give mule deer, elk, bighorn sheep and black
bear three variants each. The catalog retains the existing species identities
and rotation schedule. All eight packed previews passed, and the live library
returned all eight thumbnails in four groups of three. Owner readiness and
the host monitor reported ready after the art-only reload on 0.19.2.
Catalog SHA-256 is `bf81069a63bbc021cf67841419b65bf4612781c007be839274f8684b1093dfdc`.
The previous catalog is under `/docker/backups/emviary-deployments/colorado-wildlife-variants-20261109T185352Z`.
Physical display of these compositions remains unconfirmed.

## November 9 Colorado wildlife expansion

The live 0.19.2 library now includes 16 new illustrations covering ten new
Colorado species and a black-phase red fox. All 16 packed Spectra 6 renders
passed, as did 42 focused tests. Live thumbnails and variant groups were
verified, and owner readiness and the host monitor reported ready.
The live catalog SHA-256 is `a3c87ddd034d514c338f26fbbb39a35e6616c31655be9321325761fbd8b2c299`.
The previous catalog is under `/docker/backups/emviary-deployments/colorado-wildlife-20261109T183609Z`.
Frame display of the new compositions remains unconfirmed.

## November 9 Wally artwork

Added four Wally portraits to the local and live catalogs on `emviary:poc-071`.
The 21 focused tests and all four Spectra 6 packed render checks passed. The
live library returned all four thumbnails and tomorrow's 800 × 480 preview.
No physical display confirmation was collected. The previous live catalog is
in `/docker/backups/emviary-deployments/wally-art-20261109T170406Z`.

The catalog reload rebuilt today's scheduled image without a slot error.
Readiness compared its new forecast timestamp against today's past wake and
flagged preparation overdue.

Fixed in 0.19.2 (`emviary:poc-072`, source `99eedaa`). Readiness now uses
on-time scheduled job evidence for past wakes and validates the current slot
for upcoming wakes. All 86 focused tests passed. On an isolated production
snapshot the previous image flagged overdue, the new image cleared it, and
removing on-time job evidence restored the warning. Live owner readiness and
the host monitor reported ready. All four Wally entries remained visible.
Private rollback is under `/docker/backups/emviary-deployments/readiness-after-wake-20261109`.

## November 6 health remediation

Production: application 0.19.1 / emviary:poc-071, source c4dec68.
See [health fixes](research/HEALTH_FIXES_2026_11_06.md) for fresh backup evidence,
readiness monitoring, shared maintenance changes, rollback and the timer-triggered
cold-backup interruption. Prior October 28 observations below are historical.


Last publication review: October 27, 2026. This is a resume index, not a release or live-health certificate.

## Start here

Read AGENTS.md and the relevant source/setup/quality documentation. Recheck the current branch, working-tree status and task authorization before acting. Existing uncommitted work may belong to another task.

## Latest operational health review

October 28, 2026: source main `98d8a2455b33d74dcdfb557dc6e3dda6c3aaafa4` was
inspected against production 0.19.0 / `emviary:poc-070` /
`0918cfd1084a9effac5a3483b1d4210b4b4f538e`. Service, database, artwork integrity,
daily device reports, weather sources and today's recorded backup verification
are healthy. Main's recipient guide remains undeployed.

The shared-host cold backup runs at the same 04:15 wake as the frame and caused
about two minutes of service downtime. The 04:45 host updater failed on a missing
image reference. The frame still explicitly permits immediate prereleases.
No live configuration, policy, container lifecycle or firmware changes were made.
See [the health report](research/HEALTH_CHECK_2026_10_28.md) for evidence,
monitoring/retention gaps, recommendations and physical-verification limits.

## Current evidence

Reviewed on branch `codex/review-pending-work`, based on main revision
`db612562837dfe91c1332752a5daaeb1daf3be16`. The tested application and test
revision is `a79c1084f08b06a1e75b3c2a15ffe11ffcf953e6`; the publication follow-up
adds only this handoff and project instructions.

Ready source changes: account-free printable recipient guide, stable/seven-day
new-frame firmware defaults, clearer reconnect advice, preserved saved update
preferences, and gallery-index migration/query-plan regression coverage. The
previous path-cleanup documentation is already on main and was not republished.

Verification on the tested revision:

- Ruff lint and formatting pass for `src`, `tests` and `tools`.
- Full Python suite: 423 passed, one existing Starlette/httpx deprecation warning.
- Saved automatic, manual and disabled update policies survive a settings save,
  application restart and authenticated update discovery.
- Hidden-browser guide checks: Print calls `window.print()`, no JavaScript errors,
  no horizontal overflow at 1280/390/320 px, and readable one-page Letter PDF.
- The firmware submodule and release pin are unchanged. Button wording was
  checked against pinned source, not a new hardware test.

Original uncommitted files were copied into an isolated review branch; the
canonical checkout and other local branch histories were preserved during review.

No deployment, firmware update, panel refresh or live policy change was performed.
Destination Wi-Fi, charging kit, battery endurance, overnight operation and
physical recovery remain separate handoff gates. See the dated gift readiness
plan, then gather fresh live evidence before any deployment or physical release.

## Update after material work

- Task and scope, including any pending user decision.
- Exact checkout/branch/revision and relevant PR or artifact.
- What changed and which unrelated work remains.
- Checks actually run, results, and limits of the evidence.
- Deployment/physical observations separately, with date if performed.
- Next concrete step and rollback/approval scope when applicable.

Keep tokens, credentials, customer data and raw diagnostics outside this document.
