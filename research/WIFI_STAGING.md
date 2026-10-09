# Saved Wi-Fi staging

Current controls: [cloud Settings](https://emviary.majjix.com/manage/settings)
shows Saved Wi-Fi networks directly, with a Wi-Fi networks shortcut on each
frame's overview. The local page at `http://emviary.local` also has Add network
and Save networks while the frame is awake. Firmware v0.7.6 retains the five-profile
store, write-only passwords and network fallback. The device had one saved
network before the firmware audit; multiple-profile capacity was not removed.

Application 0.9.2 and firmware v0.7.6 show the complete saved list in both UIs,
including profiles created directly on the device. The frame reports only SSIDs
and password-presence flags over the existing authenticated image request; no
additional polling or wake is introduced. The owner page shows the last reported
inventory, connected network at that report and a timestamp. Cloud-managed
profiles remain a separate section so pending changes are not mistaken for
confirmed device state. Local saves reach the cloud on the next artwork fetch;
Refresh picture synchronizes the list while the frame is awake.

Existing device profiles remain when cloud networks are added. Local settings
show and replace the complete saved list; blank existing passwords retain their
saved values. Password fields use `autocomplete="new-password"` to discourage
account-password autofill. Inventory is limited to five unique, valid SSIDs and
private owner views. New firmware is required before device-only profiles can
appear in cloud inventory.

Application 0.4.0 adds authenticated, CSRF-protected cloud Wi-Fi management.
Firmware 0.4.0 adds ordered saved profiles; the 0.4.1 follow-up moves scan records
onto the heap because the E1002 main task has a 6 KiB stack.

The frame stores a validated list of one to five profiles in one atomic NVS
value. Existing single-network credentials remain a migration source. Credentials
are write-only in device and owner UIs and excluded from status and render plans.

Cloud configuration is additive: requested profiles precede existing recovery
profiles, and explicitly removed cloud SSIDs are forgotten. The configuration
travels in the authenticated private image response, bounded to 1900 bytes.
Local configuration replaces the ordered set. Saving never tests or changes the
current connection; selection happens on the next wake.

One scan identifies advertised saved networks. Visible profiles are attempted in
order before hidden or unavailable profiles. Multiple-profile association attempts
share a 60-second budget, with normally 12 seconds per profile. Unattended failures
retain the panel and credentials; interactive boots retry while awake. DHCP is
recommended for moving between locations.

Validation before release: 39 application tests, 69 webapp tests, webapp production
build, lint, and 13 firmware credential/retry tests passed. The E1002 v0.4.0 build
and GitHub OTA succeeded. A temporary unavailable destination was added through
production management, delivered on a real image fetch, and appeared first in the
device list alongside its retained recovery network. HTTP configuration rejected
an empty list and retained the prior saved profiles.

Pre-deployment consistent backup: `20261008T180149Z`; release rollback assets
are in `/docker/backups/emviary/release-poc-011`. Application image is
`emviary:poc-011`, implementation commit `388a99a`. Firmware digest and revision
are recorded in `firmware.lock.json`.

Hardware fallback validation: both profiles survived a USB restart. With the
unavailable staged SSID first, the frame scanned and joined its existing network
in 4.7 seconds. The original 03:15 cron and deep-sleep setting were preserved.

Final release verification: v0.4.1 passed the E1002 build and automatically
installed from GitHub with full SHA256 verification. Its wake log selected
profile 2 of 2 and reconnected in 4.7 seconds. The temporary cloud profile was
removed through management and a real refresh; only the original saved network
remains. Both local hostnames respond with v0.4.1. Temporary cloud test settings
were restored to device-managed defaults.

## Complete inventory verification, 2026-10-09

Application 0.9.2 (`emviary:poc-033`) and E1002 firmware v0.7.6 were deployed.
The release checksum, source revision, image size and unchanged partition table
were checked before the installed frame upgraded successfully through GitHub OTA.
All 119 backend tests, lint and 197 firmware host tests passed; the ESP-IDF 6.0
board build passed. Backend tests cover nested secret exclusion, escaped SSIDs,
five-profile wire bounds, private inventory and reporting on HTTP 200 and 304.

On the physical E1002, four temporary open profiles were added alongside the
original password-protected profile. The local recovery UI displayed all five,
including the connected profile and password-presence flags. A real image fetch
reported all five to the authenticated cloud settings UI. The original single
profile and its saved password were restored; the image URL, nightly cron, frame
token-presence flag and deep-sleep setting were unchanged. The final refresh
reported the restored list. Automatic firmware updates remain enabled.
