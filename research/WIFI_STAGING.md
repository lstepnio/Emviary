# Saved Wi-Fi staging

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
