# Emviary browser USB recovery

The authenticated Recovery page repairs a reTerminal E1002 over a laptop's USB
port using Web Serial. The service delivers immutable firmware files; all serial
communication and flash writing run locally in the browser. No device logs or
credentials are sent to the server. Chrome and Edge on a laptop are the supported
path. The browser must allow the user's explicit serial-port selection.

## Repair and start fresh

1. Download the existing frame's private recovery import file on Recovery.
2. Connect USB with a data cable; power switch on. Close other serial programs.
3. Prepare the installer. All four parts must pass their size and SHA-256 checks.
4. Confirm E1002, click Connect and restore firmware, and select its USB port.
5. Leave the tab and cable in place through writing and per-part flash MD5 verification.
6. Confirm restart and picture. Green wakes the local management interface; press
   RIGHT once to fetch new artwork, then confirm updated Last contact and the
   physical picture. If setup appears, join the PhotoFrame hotspot, configure
   2.4 GHz Wi-Fi, and import the saved recovery file.

Normal repair preserves NVS (Wi-Fi and settings) and LittleFS on the Emviary
partition layout. Start fresh is an explicit full-erase choice with confirmation;
it removes all local data, so Wi-Fi and the cloud connection must be restored.
Cloud policy, artwork and special days remain intact. Repair writes blank OTA
selection data so the verified app in ota_0 boots, rather than leaving a possibly
broken ota_1 selected. Do not use a merged binary: its gaps would overwrite NVS.

The chip and detected flash size must be ESP32-S3 and 32 MB. This cannot distinguish
an E1002 from every other ESP32-S3 board with the same capacity; the user must
confirm the device model. Secure-download, secure-boot and flash-encryption devices are refused before writes. A cancelled port
chooser performs no writes. Interrupted flashing releases the port and can be
retried. Successful flash followed by a reset failure is reported separately.

## Bundle provenance and reproducibility

The packaged bundle's `manifest.json` records the firmware release, exact build
commit/run, offsets, lengths and SHA-256 hashes. Bootloader and application come
from the same release/build, with the CI partition table. OTA selection is 8192
bytes of erased flash, matching ESP-IDF's ota_data_initial.bin. The bootloader
and app retain their published headers unchanged.

| Part | Offset | Purpose |
| --- | --- | --- |
| bootloader.bin | 0x0000 | E1002 bootloader with OTA rollback |
| partition-table.bin | 0x8000 | Original E1002 32 MB layout |
| ota-data.bin | 0xf000 | Reset OTA selection to ota_0 |
| application.bin | 0x20000 | Emviary firmware |

The server checks bundled file hashes before serving the manifest. The browser
checks them again before opening USB, rejects invalid ranges and external URLs,
and requests MD5 flash verification. Files are streamed, not kept in server RAM.
The browser module is loaded only on Recovery. It is a bundled, self-hosted
esptool-js 0.7.0 plus SparkMD5 3.0.2, built using the pinned npm lockfile.

```sh
npm ci --prefix web-recovery
npm test --prefix web-recovery
npm run build --prefix web-recovery
```

CI repeats tests and confirms a rebuilt bundle matches the committed file.
Upgrading recovery firmware is an explicit release change, not a live latest-tag
lookup. Replace all matching parts, verify hashes/geometry, update the manifest
and version references, test and deploy together. Do not mix the installed legacy
bootloader with an app from another build.

Sources: [Espressif esptool-js](https://github.com/espressif/esptool-js),
[Seeed E1002 guide](https://wiki.seeedstudio.com/getting_started_with_reterminal_e1002/),
[ESP-IDF OTA boot selection](https://docs.espressif.com/projects/esp-idf/en/stable/esp32s3/api-reference/system/ota.html).
Dependency licenses are saved alongside the npm project. These browser recovery
paths have automated coverage and a [physical two-slot failure recovery test](../research/USB_RECOVERY_HARDWARE_2026_10_12.md). That test qualifies normal
repair on the E1002 used; interrupted flashing and full erase/reprovisioning are
separate, untested scenarios.

Maintainers can package the verified release download with:

```sh
uv run python tools/package_usb_recovery.py RELEASE_DIRECTORY --version v0.8.3 --build-url GITHUB_BUILD_URL
```
