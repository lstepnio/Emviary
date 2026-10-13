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

Service: 0.15.3. Firmware candidate: v0.8.6, source `dd9a973bff4de055af9e3c9b8350a53d1930c473`, official ESP-IDF v6.0 build [38352231006](https://github.com/lstepnio/Emviary-firmware/actions/runs/38352231006). Immutable bundle has four verified public firmware regions and excludes NVS and LittleFS.

274 backend tests and 95 controller/browser/transport tests pass. These exercise healthy verification, slow/legacy startup, retry budgets, cancellation, disconnected/occupied ports, wrong devices, corrupted artifacts, stale sessions, pending binding protection and cloud/panel evidence. These tests do not qualify host drivers, electrical timing, damaged hardware or actual picture retention. Live hardware results are recorded separately after deployment.

The first live v0.15.0 check exposed closed UART reuse after a timeout, before any firmware writes. v0.15.1 recreates closed UART transports automatically, with a real timeout regression test. Terminal failed/paused flows release their browser renewal timer so the server lease expires when idle.

The next hardware test verified v0.8.5 firmware-region repair and application startup; a correlated cloud picture request was recorded, but later image/panel acknowledgments were not established. The frame was subsequently disconnected by its owner. This result is incomplete, not a successful physical recovery.

v0.8.6 removes synchronous NVS, filesystem and charger work from the UART responder and uses a zero-wait OTA state read. Bounded RAM diagnostics expose download progress and ACK status; allocation/bounds failures return explicit errors instead of silently dropping replies. This removes identified blocking paths but does not prove the cause of the incomplete v0.8.5 run. Normal operation retains quiet logging.

The service can register a new validated boot under the same active recovery session. It requires owner authorization, CSRF, matching device identity, firmware and immutable bundle; old image/cloud/panel evidence is cleared. Pending configuration credentials survive the transition. An unknown first-use device is tentative until an authenticated frame request establishes durable identity.

The v0.8.6 run verified the downloaded body with a correlated cloud image acknowledgment. Panel completion was not established before a serial reply timeout. Service0.15.3 now preserves an open UART after a completed read-only STATUS write whose reply times out, and retries polling within the original connection deadline. Pending writes, cancellation and disconnection still release the port. This prevents a missing status reply from triggering an early reset during refresh.
