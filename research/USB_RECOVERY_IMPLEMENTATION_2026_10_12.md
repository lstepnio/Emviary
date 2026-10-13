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

Service candidate: 0.15.5. Firmware candidate: v0.8.7, source `27973faeacf2c89bc60a5bf8dba2b27fc322f780`, official ESP-IDF v6.0 build [38356326318](https://github.com/lstepnio/Emviary-firmware/actions/runs/38356326318). Immutable bundle has four verified public firmware regions and excludes NVS and LittleFS.

274 backend tests and 102 controller/browser/transport tests pass. These exercise healthy verification, slow/legacy startup, retry budgets, cancellation, disconnected/occupied ports, wrong devices, corrupted artifacts, stale sessions, pending binding protection and cloud/panel evidence. These tests do not qualify host drivers, electrical timing, damaged hardware or actual picture retention. Live hardware results are recorded separately after deployment.

The first live v0.15.0 check exposed closed UART reuse after a timeout, before any firmware writes. v0.15.1 recreates closed UART transports automatically, with a real timeout regression test. Terminal failed/paused flows release their browser renewal timer so the server lease expires when idle.

The next hardware test verified v0.8.5 firmware-region repair and application startup; a correlated cloud picture request was recorded, but later image/panel acknowledgments were not established. The frame was subsequently disconnected by its owner. This result is incomplete, not a successful physical recovery.

v0.8.6 removes synchronous NVS, filesystem and charger work from the UART responder and uses a zero-wait OTA state read. Bounded RAM diagnostics expose download progress and ACK status; allocation/bounds failures return explicit errors instead of silently dropping replies. This removes identified blocking paths but does not prove the cause of the incomplete v0.8.5 run. Normal operation retains quiet logging.

The service can register a new validated boot under the same active recovery session. It requires owner authorization, CSRF, matching device identity, firmware and immutable bundle; old image/cloud/panel evidence is cleared. Pending configuration credentials survive the transition. An unknown first-use device is tentative until an authenticated frame request establishes durable identity.

The v0.8.6 run verified the downloaded body with a correlated cloud image acknowledgment. Panel completion was not established before a serial reply timeout. Service 0.15.3 now preserves an open UART after a completed read-only STATUS write whose reply times out, and retries polling within the original connection deadline. Pending writes, cancellation and disconnection still release the port. This prevents a missing status reply from triggering an early reset during refresh.

Continuing a previously attempted session now receives one bounded wake and two post-verification restart attempts per run, while retaining the ten-minute overall active budget, identity constraints and three firmware-transfer attempts. Lifetime wake/reset counts remain metrics rather than preventing a later verified restart.

The E1002 enables automatic light sleep, which gates peripheral interrupts unless a suitable wake source or power-management lock is held. Recovery had guarded deep sleep but had no corresponding light-sleep guard. A v0.8.7 candidate adds an explicit recovery-only lock and fixed UART clock configuration; normal scheduled battery operation must remain unchanged. See [ESP-IDF power management](https://docs.espressif.com/projects/esp-idf/en/v6.0/esp32s3/api-reference/system/power_management.html).

Live service 0.15.4 verified all firmware regions for v0.8.7, but browser application startup was not established. A same-port direct serial probe received valid v0.8.7 HELLO replies at 1.3, 5.4 and 12.3 seconds after reset; those frames pass the browser CRC/parser. The browser reset settled for 350 ms and closed/reopened on a missing HELLO reply, potentially resetting before a delayed listener could answer. Service 0.15.5 keeps a completed read-only HELLO request on the same UART for bounded re-probes and uses a one-second reset settle. This source defect is confirmed; the startup timing hypothesis still needs hardware qualification.

The controller HELLO outer deadline is longer than the transport reply deadline, allowing the transport to preserve a completed read-only request before any outer cancellation. The actual browser-entrypoint regression drops the first startup command, waits the genuine four-second reply deadline, and succeeds on the same open bridge without reset or ROM writes.

## Live qualification, 2026-10-13

Service 0.15.5 (`emviary:poc-059`, source `41cc9995f7be842896df875cf7757cce26e09843`) passed deployment health checks with the unchanged 512 MiB container limit. Saved frame policies and collection counts matched the usual independent pre-deployment backup. Firmware v0.8.7 was installed and all public recovery regions verified through the browser. A subsequent check skipped firmware writing and reached the physical-picture confirmation screen.

The correlated boot requested artwork at 06:51:01 UTC, verified its body at 06:51:06 UTC, and acknowledged panel refresh at 06:51:37 UTC. Cloud telemetry reports v0.8.7 and two saved Wi-Fi profiles with password presence. Bounded same-session cloud verification retries completed without another reset or firmware write. The owner has been asked to confirm the visible picture; physical acceptance and final session completion remain pending.

Validation: 274 full backend tests, 29 scoped recovery tests after the final service patch, 102 browser/controller/transport tests, 246 firmware host tests, and both official GitHub CI runs passed. This does not establish sleep-current or battery-life measurements.
