# Guided USB recovery

October 12, 2026. Application 0.14.0, firmware v0.8.4.

The default flow is **Recover frame**, Chrome's required USB-port selection,
then confirmation that the physical picture is visible. Firmware downloads and
SHA checks are automatic on the Recovery page. The flow preserves settings first,
shows progress in plain language, and hides manual procedures and backups.

## Escalation

1. Download and validate the immutable E1002 firmware bundle before opening USB.
2. Connect, verify chip/memory/security, restore four separate firmware parts and
   verify each flash MD5. Retry transient connection/write failures up to three
   times on the same authorized port; wrong hardware or custom security stops
   immediately. An interrupted cable still requires reconnecting it.
3. Restart, then poll the cloud for a new authenticated contact from the selected
   frame running the expected firmware. A pre-existing contact or another frame
   cannot pass. If necessary, try one further restart and wait again. Cloud checks
   do not poll the ESP32 or write its flash. Missing cloud artwork stops verification
   rather than recommending a destructive reset for a server problem.
4. If still offline, ask for green wake or offer **Restore from cloud**. This is an
   explicit escalation: replace local Wi-Fi/settings/cache only with checkbox and
   confirmation. An unknown local Wi-Fi network requires its password; saved cloud
   passwords can be reused without displaying them.
5. Build a fresh NVS image for exactly 0x9000..0xf000, containing this frame's cloud
   binding, up to five Wi-Fi profiles, timezone/schedule and logging off. Generate
   using pinned Espressif tooling in a bounded, short-lived subprocess, with stdin
   credentials and stdout binary. No plaintext temporary files, console secret
   output, extra backup or permanent generator process. Only the reset path writes
   this settings image. A private local-management password is derived from the
   device token and disclosed under optional details after cloud restoration.
6. If the private device token is missing or unusable, cloud restoration creates
   a replacement binding without an owner CLI. File/DB updates use private atomic
   writing and compare-and-set protection; failed generation changes neither the
   credential nor policy. Existing valid credentials remain unchanged.
7. Verify the cloud contact and show its delivered artwork, then ask whether the
   actual panel picture appears. Software cannot observe a defective physical panel.

New Wi-Fi details entered for restoration are retained in cloud settings. Existing
artwork, calendar, locality, display settings and daily wake are retained. Network
capacity is explicit; a sixth saved profile is rejected rather than silently dropping
an existing network. Temporary browser NVS buffers are zeroed after use.

Firmware v0.8.4 performs one startup artwork fetch when an interactive boot has USB
power and URL mode. It also covers a late Wi-Fi connection. Battery-powered
interactive wakes keep the previous behavior. There are no new firmware logging
writes or background tasks. The exact v0.8.3 quiet bootloader is approved for future
application OTA compatibility; normal OTA still leaves the bootloader untouched.

## Validation

235 Python tests and 12 browser-recovery JavaScript tests passed. Coverage includes
consent/CSRF/origin checks, independent NVS entry CRC inspection, existing credential
preservation, missing-token binding restoration, failed preparation atomicity,
three-attempt bounds, adaptive baud rates and read/digest preflight, terminal hardware refusal, and freshness/target-version checks.
Firmware CI passed 244 host tests, six packaging checks and an ESP-IDF v6.0 build.
The v0.8.4 recovery files match the published manifest and GitHub asset digests.
The complete wheel contains all four files and the isolated settings worker.

Deployment and physical acceptance will be appended after installation. The earlier
[two-slot failure test](USB_RECOVERY_HARDWARE_2026_10_12.md) qualifies the underlying
browser flashing path; it does not by itself qualify this new automation or factory
reset provisioning.

Sources: [Espressif NVS generator](https://github.com/espressif/esp-idf-nvs-partition-gen),
[esptool-js](https://github.com/espressif/esptool-js),
[Web Serial transport](https://espressif.github.io/esptool-js/docs/classes/Transport.html).

## Adaptive transfer speed

ROM sync uses 115200 baud. Transfers try 460800, then 230400, then 115200.
Each attempt resets back to the known ROM baud, uploads the stub and negotiates
the chosen rate. Before erasing, a 16 KiB application-area read is checked against
the stub's trailing MD5 packet; that packet is consumed before the next command.
Per-part flash MD5 remains mandatory. Probe buffers are cleared, not backed up.
A successful rate is remembered only for this recovery tab and USB adapter;
optional session storage contains no credentials. All retries and checks are
deterministic, with no AI calls.

On the current E1002/adapter, known-byte read probes passed at both 230400 and
460800, in 2.44 and 2.63 seconds including connection/reset overhead. These small
reads establish compatibility, not full-write throughput. The prior isolated
460800 packet error demonstrates why preflight and fallback are still needed.
Full browser write speed and end-to-end timing are measured during acceptance.
