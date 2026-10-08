# Display blanking investigation, 2026-10-08

The owner reported repeated blanking after the first battery sleep/wake test.
The first cloud image had been physically confirmed as good. The test observed
USB disconnected, about 98 percent charge, a scheduled wake delivering HTTP 200,
and a later wake returning HTTP 304. Readback showed the normal 03:15 Denver
schedule restored and no recorded fetch error. These observations do not establish
that the panel retained its picture throughout sleep.

At investigation time the frame was unreachable and no USB serial port was present.
A request to reconnect USB and distinguish temporary refresh flashing from a
persistent white screen is pending. The trigger for blanking remains unconfirmed.

Two defects are confirmed by the pinned v2.19.0 source:

- `display_manager_clear()` removed the current-image state without invalidating
  its stored HTTP ETag. A subsequent unchanged response could leave a cleared
  screen blank. The fork now invalidates that marker before clearing.
- Its clear path called `epaper_clear()` and then `epaper_display()`. The E1002
  Spectra driver already refreshes inside `epaper_clear()`, causing two white
  refresh cycles. The fork instead fills the paint buffer and refreshes once.

Neither source defect proves an unsolicited clear occurred. The E1002 right
button clears; its left button rotates; its green button wakes configuration.
Normal full color refresh takes about 30 seconds. Deep sleep should retain art.

The patch is committed to `einkartifact-firmware`, revision `a514a2c`. A dedicated
E1002 workflow builds with ESP-IDF 6.0, matching the upstream build requirement.
The installed local ESP-IDF 5.4.1 cannot build this upstream revision because it
lacks the multiple-wakeup-causes API. No compatibility workaround was added.
GitHub build run 37744229866 succeeded. After USB reconnection, the device
responded on Wi-Fi, reported 100 percent charge and USB charging. Its existing
application was in OTA slot 1, at 0x3a0000. A private 40 KiB configuration-region
backup completed. The full-slot application read failed after a USB transfer
error, but a 2 MiB application-only retry succeeded; its first 2,070,288 bytes
match the official E1002 v2.19.0 release exactly.

The patched 2,052,352-byte application was written only at 0x3a0000. Esptool
reported hash verification. Boot then reported `dev-a514a2c`, E1002 and ESP-IDF
6.0. Wi-Fi, image authentication, TLS pin, deep sleep and the 03:15 schedule
were confirmed preserved. The partition table, bootloader, NVS and storage were
not overwritten. Application SHA256:
`cf106428a894132efe97b053fe9db21412296abe253fd23a844ad409a173efaf`.

Opening the CP210 serial port reboots this board, so initial POWERON logs cannot
establish the original blanking trigger. The current partition table has no core
dump partition; a null last-crash result therefore cannot rule out prior crashes.
Temporary persistent debug logging is enabled for further wake diagnosis. A fresh
HTTP 200 refresh completed in 30.4 seconds with a single display update and no
panel error. The owner physically confirmed the picture visible and stable.
A second unchanged request completed in 2.26 seconds; serial logs recorded HTTP
304 and skipping display refresh, with the display-update count remaining one.
USB was subsequently disconnected. The frame became unreachable as expected
in sleep; physical retention on battery is awaiting owner confirmation.

The `/api/current_image` endpoint returned 404 even after the owner confirmed
visible art. That endpoint cannot be treated as a sensor of the physical panel
in this configuration.

## Required hardware validation

1. Reconnect USB and collect private serial logs without resetting the device
   first. Identify wake cause, clear events, brownouts, restarts and panel errors.
2. Force a fresh HTTP 200 image to recover the panel if its old ETag survived a
   clear. Avoid repeated full refresh requests.
3. Flash the identified E1002 build while preserving NVS and configured storage.
4. Clear once, then rotate unchanged content. Verify HTTP 200 and restored art.
5. Request rotation again. Verify HTTP 304 and no panel refresh.
6. Disconnect USB, perform one controlled timer wake, and verify art remains
   visible during subsequent sleep. Restore the nightly 03:15 Denver schedule.

Until those checks complete, the blanking report is unresolved. The owner UI
release is held while the hardware is investigated; the existing backend remains
live. Battery endurance has not been measured.
