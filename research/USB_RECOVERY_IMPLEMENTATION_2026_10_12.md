# Guided USB recovery implementation

The management recovery page has one primary action, **Check and recover**. It first asks the application for positive boot evidence, attempts one USB wake if needed, then identifies the E1002 and compares public firmware regions before replacing only mismatches. A healthy application proceeds directly to its saved Wi-Fi, verified artwork download, cloud acknowledgment and picture check.

## Escalation rules

- Use only the same selected device, bound to the known frame identity. An incompatible board, a different device, secure-boot/encrypted configuration, occupied port or competing recovery session stops before writes.
- Keep the port picker as the browser's required permission step. Reuse a previously granted adapter only when unambiguous.
- Retry transfers at 460800, 230400, then 115200 baud. Verify whole-region MD5 after writes and immutable release SHA256 before transfer. No erase-all operation is used.
- Retry failed network/image/cloud pipelines within the same boot and session before considering settings restoration. Firmware and working settings remain intact.
- Restore only the NVS settings region when configuration is demonstrably unusable and saved cloud credentials allow recovery. Otherwise ask once for the network details. Stage replacement binding credentials until a successful authenticated device fetch promotes them.
- Limit active work to ten minutes. Connection progress can extend its initial budget only on stronger positive evidence, to a three-minute maximum. Repeating status text cannot restart a countdown.
- Complete only after correlated device boot, firmware version, image digest, cloud acknowledgment and panel-driver result. Ask the owner to confirm the actual physical picture. Driver success alone is insufficient.

## Runtime scope

Recovery UART commands, temporary leases and bounded checkpoints are specific to interactive USB recovery. Scheduled battery wakes do not create this listener or diagnostic worker. Normal logs and debug remain off by default. Browser session journals contain identifiers and verification hints, never network passwords or device tokens. A reloaded journal must recheck device evidence.

## Release and evidence

Candidate service: 0.15.0. Candidate firmware: v0.8.5, source `0c4ffbbb93c53a4412ee829c6f7f912d9880ea07`, official ESP-IDF v6.0 build [38349079866](https://github.com/lstepnio/Emviary-firmware/actions/runs/38349079866). Immutable bundle has four verified public firmware regions and excludes NVS and LittleFS.

270 backend tests and 86 controller/browser/transport tests pass. These exercise healthy verification, slow/legacy startup, retry budgets, cancellation, disconnected/occupied ports, wrong devices, corrupted artifacts, stale sessions, pending binding protection and cloud/panel evidence. These tests do not qualify host drivers, electrical timing, damaged hardware or actual picture retention. Live hardware results are recorded separately after deployment.
