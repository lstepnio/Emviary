# Emviary browser USB recovery

The authenticated Recovery page repairs a reTerminal E1002 over a laptop's USB
port using Web Serial. The service delivers immutable firmware files; all serial
communication and flash writing run locally in the browser. No raw device logs or
local credential dumps are sent to the server. The authenticated service records
bounded recovery milestones and supplies private cloud configuration only when
settings repair is required. Chrome and Edge on a laptop are the supported
path. The browser must allow the user's explicit serial-port selection.

## Check first, then repair

1. Connect a USB data cable, turn the frame's power switch on and close other serial apps.
2. Open Recovery in Chrome or Edge. Files prepare and verify automatically.
3. Choose **Check and recover**. If asked, select **USB Serial** and **Connect**.
4. The installer checks the running application, wakes it if needed, repairs only
   mismatched firmware regions and reconnects using its saved settings. A healthy
   frame skips firmware writes. Failed image/cloud operations retry within the
   same session. Confirm the actual picture when asked.
5. If local configuration is unusable, the flow restores cloud settings once
   when saved credentials are sufficient. Otherwise it asks for Wi-Fi details.
   A staged replacement token keeps the previous cloud binding usable until the
   recovered device performs an authenticated fetch. No setup-network or import
   file is needed.

Progress shows the current operation, verified milestones and genuine write
progress. It does not restart a countdown after a timeout. Retries and active
work are bounded; hardware faults and missing credentials receive specific help.
The optional display check runs one test pattern and restores the saved picture
before asking for physical confirmation again.

Normal repair preserves NVS and LittleFS. Settings recovery replaces only NVS,
not the whole flash or saved picture filesystem. No erase-all or merged-image
path is exposed. The four public firmware regions are compared before writes;
blank OTA selection is used only when the repair path needs to select the verified
application in ota_0. A valid running application is not reset to ota_0.

USB identity is matched to the selected frame where known. ESP32-S3 and 32 MB
alone cannot distinguish an E1002 from every similar board. Secure-download,
secure-boot and flash-encryption devices are refused. A cancelled chooser makes
no writes. Reconnect resumes the same device and rechecks actual evidence.

See [implementation and evidence](../research/USB_RECOVERY_IMPLEMENTATION_2026_10_12.md)
and the [reliability design](../research/USB_RECOVERY_RELIABILITY_PLAN_2026_10_12.md).

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
uv run python tools/package_usb_recovery.py RELEASE_DIRECTORY --version v0.8.7 --build-url GITHUB_BUILD_URL
```
