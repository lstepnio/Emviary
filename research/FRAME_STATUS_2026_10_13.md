# Polished frame status, firmware v0.8.8

Hold the left white button for five seconds to open an on-demand status screen. Tap a white or green button to return to the cached artwork. The screen includes a crisp QR for https://emviary.majjix.com/, last successful cloud refresh in the configured local timezone, Wi-Fi signal and IP, battery/power status, next wake and firmware. Saved network information is explicitly marked last known when disconnected.

The status screen does not connect Wi-Fi, poll the service or add normal-operation flash writes. Refresh history uses RTC memory across deep sleep and is honestly unavailable after complete power loss. The old snapshot wording and diagnostic heading are removed. Raster font subsets and QR use integer scaling for the six-color panel; status is intentionally high-contrast black and white.

Validation: 251 firmware host tests passed; QR decoded from the actual C renderer in landscape, portrait and rotated previews. Official ESP-IDF 6 CI run 38429137245 passed. Service 0.15.7 packages the identical release regions for browser USB recovery. Firmware release: https://github.com/lstepnio/Emviary-firmware/releases/tag/v0.8.8. Device OTA and physical acceptance are pending.

See firmware/docs/FRAME_STATUS.md for implementation and fixture previews.
