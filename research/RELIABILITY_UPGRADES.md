# Reliability and collection upgrades, October 12, 2026

Application 0.11.0 implements release channel/delay/blocklist controls, schedule-aware
owner alerts, integrity-checked backup restore rehearsals, independent backup tooling,
recurring weekday special days with deterministic precedence, and artwork collection
filters/bulk controls/physical review states. Automatic updates remain enabled with
all releases and zero delay unless changed in management. Pixel processing is unchanged.

Firmware adds verified rollback-bootloader capability and defers pending-application
confirmation until offline subsystem initialization plus storage/heap checks pass.
A correctly hashed image is not automatically trusted merely because it starts.
The migration uses USB only for bootloader/initial compatible app activation. Future
application updates continue via OTA. Bootloader confirmation follows the
[Espressif OTA contract](https://docs.espressif.com/projects/esp-idf/en/v6.0/esp32s3/api-reference/system/ota.html).

Acceptance evidence and any remaining physical limitations are recorded after deployment.
