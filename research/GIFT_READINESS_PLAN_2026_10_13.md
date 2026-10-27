# Emviary gift readiness

Reviewed: October 13, 2026. Target: one preconfigured E1002 for Emily, with the
giver handling setup, updates and ongoing maintenance. Recipient setup and
account creation are outside the everyday experience.

## Decision

The core is substantially implemented, but the frame is not yet qualified for
an unattended gift. The remaining work is controlled release qualification,
destination testing, power expectations and a support arrangement.

The safest first handoff includes a tested USB power kit, a printed guide and
one frozen, physically accepted firmware version. Battery operation remains
available without a promised charging interval. A seven-night field run is a
release gate, not an endurance claim.

**Strengths:** local weather-free fallback, working physical previous/next
navigation, preserved pictures, per-frame credentials, rollback-capable firmware,
guided USB recovery, consistent backups and an independently verified restore copy.

**Risks:** experimental releases can currently reach the live frame immediately;
destination connectivity and long-term battery performance remain unqualified;
maintenance warnings require opening the website; the service depends on one
home server and DNS/TLS; network-based owner access currently grants broad
management access to people sharing the frame's public IP.

**Strongest counterargument:** many recent changes and passing tests can create
false confidence. A development frame that works under supervision has not yet
demonstrated predictable operation at somebody else's home. Shipping more features
before a quiet field run increases the problem.

**Better approach:** freeze a narrow operating profile, commission it once, run
the acceptance matrix, then hand over the physical package. Defer additional art
types, new dashboards and recipient configuration features.

**Confidence:** high that the architecture supports this maintained gift model;
moderate that the present hardware/software combination is ready for unattended
handoff. A clean field run, destination test and power measurements would increase
confidence. Repeated blanking, cache loss or reset-related setup loss would reduce it.

## Evidence and limits

| Area | Evidence inspected | What it establishes | Remaining limit |
|---|---|---|---|
| Live service | `emviary:poc-063`, application 0.16.1, healthy, 512 MiB limit | Current deployment and health | Health does not demonstrate future uptime or a physical picture |
| Frame | Last inspected check-in: Oct 13, 17:44 MDT; v0.8.10, seven cached pictures, rollback reported ready, previous refresh reported successful in 32.4 s | Recent device-reported state | The previous refresh report is delayed telemetry, not panel sensing |
| Offline display | Owner acceptance recorded in `OFFLINE_ROTATION_IMPLEMENTATION_2026_10_13.md`: weather absent, RIGHT changes pictures, LEFT returns | Physical acceptance for that outage/navigation test | Longer outages, destination operation and overnight retention need a field run |
| Wi-Fi | Device reported two networks with saved passwords | Credentials reached the frame | Saved credentials do not prove association at the destination |
| Recovery | Check-first browser recovery and verified bundles; 117 browser/controller/transport tests passed in this review | Automated recovery coverage | Final completion and configuration preservation on the chosen gift bundle need physical qualification |
| Backups | October 13 off-host copy reports a passed isolated restore rehearsal; Mac LaunchAgent loaded with last exit 0 | A verified independent copy exists and the scheduled job is installed | A sleeping/offline Mac can miss future copies; full hosting and secret recovery is a separate drill |
| Battery | 67 readings; 25 explicitly on battery, mixed with charging/development activity; latest 98% | Recent battery reporting | No controlled discharge cycle, measured sleep current or charging interval |
| Baseline | 297 backend tests and 117 recovery tests passed | Existing automated checks are green | Simulated and software results do not replace the physical gates below |

This review did not trigger a firmware update, panel refresh, live outage or
container deployment. Prior owner observations are identified separately from
live read-only evidence. Private network names, credentials and tokens are omitted.

## Changes implemented in this review

- New frame defaults select the stable channel and a seven-day publication delay.
  Explicitly saved preferences remain effective. The current frame still has
  automatic/all/zero-day preferences, so its gift freeze remains a commissioning task.
- Firmware settings explain the maintained-gift choice: Manual with a tested pin.
  Neither a stable label nor release age establishes physical acceptance.
- `/guide` supplies account-free, printable instructions for buttons, normal
  flashing, charging, offline art and maintainer help. It reads no frame data.
- Public navigation exposes the guide. Print layout omits web navigation.
- Missed-connection and failed-refresh guidance uses the green wake control.
  White-button navigation can stay offline during the reconnect cooldown, so it
  is not a reliable instruction for forcing a network retry.
- Regression coverage verifies release selection, retained explicit preview
  settings, guide privacy and discovery, and accurate reconnect guidance.

These are local changes on `codex/gift-readiness`, not a deployed release.

## Prioritized gaps and acceptance gates

P0 must be completed before handoff. P1 improves ongoing maintenance. P2 waits for
actual recipient feedback. Estimates below are engineering planning estimates.

| Priority | Gap | Concrete work | Pass condition | Estimate |
|---|---|---|---|---|
| P0 | No gift release freeze | Publish the reviewed service changes, qualify the selected firmware/recovery bundle, set Manual with the accepted version pinned, and retain a compatible service/data rollback snapshot | Newer preview/stable tags cannot change the gift frame without the maintainer choosing a release; installed version, bootloader, saved settings and rollback readiness recorded | 0.5 to 1 day plus qualification |
| P0 | Destination Wi-Fi is staged but untested | Test the exact router, 2.4 GHz network and intended frame placement; use DHCP; test router restart and return from an outage | Three successive online wakes succeed at the destination; nightly delivery and cold-start reconnect work without local setup; network inventory is preserved | 0.5 day on site |
| P0 | Battery promise is unsupported | Include a tested 5 V USB power adapter rated at least 1 A and the tested cable; check charging and charge-to-battery transitions; measure battery-side sleep and wake energy if runtime is advertised | Charging works with the actual kit; unplugging preserves the picture; any stated interval is supported by a controlled cycle or a measured energy budget with a margin | 0.5 day for the kit; longer for runtime qualification |
| P0 | No uninterrupted field acceptance | Run the frozen frame for seven consecutive nights at the destination or its exact network equivalent, without USB diagnostics or development refreshes | All scheduled pictures appear, no persistent blanking or unexpected setup screens, no unplanned reset/update, cache persists, and battery behavior is recorded | Seven calendar nights minimum |
| P0 | Maintenance alerts are web-only | Choose a maintainer notification channel, then implement bounded, deduplicated warnings for missed connections, low battery, failed OTA and stale independent backups | A controlled fault reaches the giver; recovery sends one resolution; unchanged faults do not flood notifications; failed contact is never described as a sensed blank panel | 0.5 to 1.5 days after channel selection |
| P0 | Shared-network access conflicts with the maintenance model | Disable trusted-network owner access before gifting; retain password-based giver management; review public sharing and personalized occasion visibility | A device on the recipient's network cannot obtain owner access without the owner password; the recipient guide and intended public art still work | 0.25 day |
| P0 | Printed and physical handoff incomplete | Print the guide, add the giver's preferred contact privately, include the tested cable/adapter and stand, identify the buttons and power switch, prepare a welcome picture, and test transport-style power-off/on | Someone unfamiliar with the project can turn it on, change a picture, charge it and find help using only the package; secrets and recovery imports stay in the giver's private kit | 0.5 day plus one rehearsal |
| P0 | Backend restore is not full hosting recovery | Restore the verified copy in an isolated environment, check secret recovery/rotation, Caddy/TLS/DNS configuration and compatible image retrieval; confirm the backup job runs after Mac sleep | A fresh environment serves valid authenticated artwork using privately recovered or rotated credentials; recovery does not depend on undocumented state on the old server | 0.5 to 1 day |
| P0 | Whole artwork library lacks physical acceptance | Select a small gift-safe set from existing art; check representative solo, pair/trio, wildlife, dark/light and occasion compositions on the actual panel | Names and greetings are legible, colors and margins acceptable, no cut-off content; unreviewed variants can be excluded without expanding the library | Eight representative pictures over normal use |
| P1 | Diagnostics can confuse support | Rehearse long-LEFT status, QR scanning, return to art, and maintainer readback; keep reported connection/display state distinct from a photograph | Recipient can send a useful status photo; maintainer identifies the relevant remedy without reflashing for a network/provider outage | 0.25 day |
| P1 | Latest data can be mistaken for current data | Surface age of battery, network, offline-cache and backup observations; add a maintainer-only summary of pending settings versus device-reported state | A stale reading or merely staged network cannot look like a fresh, verified result | 0.5 day |
| P1 | Recipient preferences not yet rehearsed | Review bird count, name legibility, region/forecast, wake time and enabled special days; check date overlaps and one-time versus annual intent | Giver signs off the exact profile, and one unsupervised recipient-style review finds no confusing message or unwanted occasion | 0.25 day |
| P2 | Unknown real-world preferences | Gather feedback after handoff on charge reminders, refresh delay and desired art | Add changes only when observed use justifies them | After two to four weeks |

The exact deadline has not been supplied. The safe schedule is implementation
and commissioning first, followed by the seven-night run. A material firmware,
cache, sleep or networking change restarts the affected qualification. Copy-only
help edits do not require restarting an unrelated battery experiment.

## Failure qualification matrix

Run in a controlled test window with a restore step. Avoid repeated rapid panel
refreshes. Existing unit fixtures cover many faults; the following are the
recipient-facing physical acceptance checks, not claims that all were performed.

| Scenario | Expected behavior | Evidence to capture |
|---|---|---|
| Normal nightly wake on battery | One prepared picture appears and the frame returns to sleep | Before/after panel observations, expected local wake, delayed telemetry, power behavior |
| No picture change / HTTP 304 | Existing picture remains; no unnecessary repaint | Stable panel, unchanged-response report |
| Router unavailable, DNS failure or HTTPS service unavailable | Bounded attempts, then saved ordinary art with no forecast; later reconnect | Elapsed time, physical art/weather check, offline telemetry after recovery |
| Repeated offline nights | Display schedule continues; network probes back off; valid cached navigation remains usable | At least two offline scheduled wakes, LEFT/RIGHT checks, reconnect result |
| Forecast/bird provider failure | Art remains available; expired or missing weather is omitted; no invented freshness | Prepared output and visible picture, provider outcome |
| Button during refresh | One latest navigation is honored after the current refresh; no persistent blank | Physical sequence and final requested direction |
| Low battery and empty battery | Critical scheduled refresh holds the picture; charging restores response | Reported level plus measured voltage, visible art, actual charge recovery |
| Power loss / shipping power switch cycle | Saved Wi-Fi, cloud credentials, cache and normal controls survive | Private configuration readback, cache count, physical wake/reconnect |
| Interrupted OTA | Known-good firmware remains or rollback occurs; art and settings survive | Controlled test on a spare/test window, installed version and physical picture |
| USB recovery with cloud unavailable | Targeted network remedy; no false success, destructive erase or repeated firmware rewrite | Browser/session evidence and subsequent physical completion |
| Corrupt/missing cached entry or full filesystem | Skip the damaged entry or admission; preserve valid art and settings | Existing filesystem fault fixtures plus bounded physical test where warranted |
| Server rebuild / restored backup | Correct picture service, dates, token authentication and device reconnect return | Isolated restore results, private credential procedure and a physical refresh |

## Handoff record

Keep the detailed record private. Record the service tag/source revision, firmware
tag/digests, board/bootloader and rollback support, approved configuration revision,
destination test, cache count, charge kit, artwork sample review, seven-night
results, recovery result, backup/secret recovery and maintainer contact. Add a
photo of the packed kit and first intended picture.

The release decision is **ready** only after all P0 rows have evidence. Tests,
saved Wi-Fi, a healthy container and a high battery reading are inputs to that
decision; none substitutes for it. If the date arrives first, hand over only the
explicitly qualified power/operation profile and agree on the remaining support
work. Do not promise three-month operation from the vendor headline.

Hardware facts and charging cautions were checked against
[Seeed's E1002 guide](https://wiki.seeedstudio.com/getting_started_with_reterminal_e1002/).
The manufacturer's default-firmware battery claim does not establish endurance
for Emviary's firmware, refresh frequency or Wi-Fi conditions. Vendor stock-firmware
button/reset instructions are not instructions for the Emviary gift profile.

## Validation of this review

- Existing baseline: 297 backend tests and 117 recovery tests passed.
- Changed-path checks: 31 focused tests passed; lint, formatting and diff checks passed.
- Final full suite: 300 backend tests passed; the unchanged recovery suite passed
  all 117 tests. The backend suite reports one pre-existing Starlette/httpx
  deprecation warning, with no failures.
- Real Chrome reflow: `innerWidth` and document `scrollWidth` match at 320, 390
  and 1280 pixels. The guide reports no console errors or warnings. The actual
  print button invokes printing. The generated US Letter PDF has one page,
  12 mm margins and a visually reviewed final render.
- The plan and recipient PDF are review artifacts. Publish the service before
  relying on the guide's printed online address.
- No physical gift qualification result was generated by this source review.
