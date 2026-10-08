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

The patch is committed to `emviary-firmware`, revision `a514a2c`. A dedicated
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

## Follow-up investigation, 2026-10-08

The owner again described finding the frame white over time and believes this
also occurred with earlier firmware. It is not yet established that the behavior
recurred after the patch. On reconnecting USB the owner reported the picture
already visible, before any new image request from this investigation.

The persisted debug log was recovered before another redraw. It records one
wake attributed to the rotate-button input (GPIO 5), a completed display refresh
of about 27 seconds, and a return to sleep. It records no clear-button wake or
clear-screen action in the captured interval. An attributed GPIO wake does not
prove a person pressed that button. Refresh whitening could explain a transient
observation, but does not explain finding the frame persistently blank.

A controlled manual sleep request was issued while powered by USB, without an
image request. The device became unreachable and the owner confirmed that the
picture remained visible after the two-minute sleep-only check. This establishes
short-term retention for that transition, not overnight battery retention.

No further firmware change was applied. Longer battery-only retention and a
freshly captured actual blanking event remain necessary. The device was left
sleeping with its 03:15 Denver schedule unchanged. Saved logs remain private.

## Captured white-screen event, 2026-10-08

The owner reported a white panel after the short sleep-retention test. The device
was reachable on Wi-Fi, so logs were downloaded before a reset or image request.
They show a green/BOOT-button wake at external-RTC time 07:37:50, followed later
by `Clear button pressed, clearing display`. The white refresh completed and the
saved image identifier was cleared. The server's last image contact was still
13:03:19 UTC, so no server image delivery caused this blanking event.

The owner answered that the clear button may have been touched. This makes an
intentional clear action a plausible explanation for this captured event, without
establishing the cause of every historical white-screen report. The firmware
currently accepts a short clear-button press. Green wake does not restore art;
rotation is required after a clear. The raw diagnostic log remains private.

After the owner pressed green wake, an explicit API rotation succeeded. The server
recorded delivery of revision 6 at 14:18:20 UTC with an empty client ETag, as
expected after a clear. Firmware logged `Display update complete` and `Image
displayed successfully`, with one 192000-byte panel transfer. Physical confirmation
was requested separately; these logs alone do not prove visible panel retention.

## Right-button disable patch, 2026-10-08

Firmware commit `04c423fca243edba5e39a0d9c816b79505beaaad` changes the E1002
`BOARD_HAL_CLEAR_KEY` from GPIO4 to GPIO_NUM_NC. The existing guards then exclude
the right button from awake input handling, deep-sleep wake masks and clear-wake
classification. Green wake and left refresh remain enabled. HTTP clear capability
is unchanged; this patch specifically disables the physical button.

The dedicated ESP-IDF v6.0 E1002 build passed in GitHub Actions run 37798849988.
Application SHA256: `260021d3c291cc49723482c74e4de90d7f580beb889660c3967e0df60c8f6475`.
A fresh private 40 KiB configuration-region backup was made. OTA sequences 1/2
confirmed active slot 1 at 0x3a0000 before application-only flashing.

The 2,052,064-byte application flash verified successfully at 0x3a0000. Saved
boot logs confirm firmware `dev-04c423f`. Read-only API checks confirmed deep sleep,
`15 3 *` rotation, Denver DST timezone rules and the TLS certificate pin survived.
Physical right-button validation was requested separately.

The owner pressed and released the right-hand button with USB connected and
confirmed: `Picture remains visible`. Awake button behavior is physically verified.
The sleep wake-mask exclusion is source/build verified; a separate physical
right-button press during deep sleep was not performed in this check.
