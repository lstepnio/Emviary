# Browser USB recovery hardware acceptance

October 12, 2026. reTerminal E1002, `emily-e1002`, firmware v0.8.3,
production application 0.13.0.

## Result

Passed the controlled two-slot application failure and normal browser USB repair.
The physical frame booted, retained both saved Wi-Fi networks and its cloud
connection, completed a cloud artwork fetch, and the owner confirmed that the
right white button displayed a different, stable bird picture. Device logging
remained disabled. No additional full flash backup was created; existing backups
and cloud configuration remained the recovery fallback.

## Failure and recovery evidence

- Matched the connected device to its existing hardware identity and verified
  ESP32-S3, 32 MB flash, no secure boot or flash encryption, and the actual
  partition table against the published recovery bundle before mutation.
- Overwrote only the first 4096 bytes of both application slots, `0x20000` and
  `0x3a0000`, with zeros. Esptool verified both writes. NVS, LittleFS,
  partition table and bootloader were outside the injected fault ranges.
- Recorded 322 repeated ROM boot sequences in ten seconds. Neither application
  slot retained a valid image header, so automatic application rollback could
  not supply a working image.
- Used the production Recovery page, prepared its immutable v0.8.3 bundle,
  confirmed E1002, and selected the frame's serial port in Chrome's native chooser.
  Normal repair was used, with full erase unchecked.
- Browser Web Serial wrote all four recovery parts and reported successful
  per-part MD5 verification and a requested restart. Terminal tools performed
  fault injection and subsequent diagnostic reads/resets, not recovery writes.
- Read back the restored first 4096 application bytes and matched them exactly
  to the published v0.8.3 binary. Rapid ROM rebooting stopped. The frame's local
  API subsequently reported v0.8.3, two saved Wi-Fi profiles, and logging false.
- A local `/api/rotate` request completed successfully; fresh cloud telemetry
  reported v0.8.3, both network profiles and rollback capability. The owner's
  subsequent physical right-button test confirmed different, stable artwork.

Private serial evidence, injection logs and the recovered overview screenshot
are in `.private/usb-recovery-hardware-20261012/`. Credentials and raw device
configuration are not included in this public report.

## Operational findings and limits

A high-speed diagnostic read at 460800 baud failed with a serial packet error.
A repeat at 115200 succeeded. The browser installer already uses 115200 baud.

Green wake opens the local management interface; it does not request new cloud
artwork. Existing e-ink pixels can remain unchanged on an unbootable device and
also on a healthy wake. Verify the local running version and a real fetch, then
use RIGHT once and confirm the physical picture. Do not infer failure or success
from unchanged pixels alone. The frame was disconnected and reconnected during
post-write verification; green wake and a controlled diagnostic reset were used.
Automatic restart without that intervention was not independently established.

Normal repair writes a working app in ota_0 and resets the OTA selector. It does
not fill both app slots. The damaged inactive ota_1 will be replaced by a future
OTA update; rollback from that update uses the recovered ota_0.

This test does not qualify interrupted browser writes, damaged partition tables
or bootloaders, full erase and Wi-Fi reprovisioning, another laptop/browser, or
power consumption. Those remain separate scenarios. No eFuses were changed.
