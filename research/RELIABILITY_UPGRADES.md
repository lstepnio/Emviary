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

## Acceptance

Application 0.11.1 is deployed as `emviary:poc-040`; source commit `27150ee`.
All 183 backend tests and 229 firmware host tests passed. The new board build
passed with ESP-IDF 6.0. Firmware v0.8.1 source is `ed2612cb0285f0e36fb221be7dbf0c2fc8296646`.

Before migration, targeted control/NVS/OTA and active-application backups were
saved privately; the old installed image matched v0.7.7's release digest. Partition
layout was unchanged. Bootloader readback matched its verified v0.8.0 digest.
A deliberately unconfirmed candidate was marked ABORTED by the new bootloader,
and the device booted v0.7.7. v0.8.0 subsequently passed offline confirmation.
The frame then installed v0.8.1 via authenticated GitHub OTA, passed the same
confirmation, and reported rollback capability plus both retained Wi-Fi profiles.
The user confirmed the picture is visible, readable and stable. The 03:15 schedule
remains unchanged. A boot-rejected version is quarantined against repeat installation;
newer corrected versions remain eligible.

A production backup and independent Mac copy passed offline restore rehearsal:
681 files, 169 active artworks, 27 event artworks, 166 retained images and one
last-delivered image. No existing backups were deleted. The private 06:30 Mac
LaunchAgent was loaded and its real invocation exited 0. Container RAM/swap limits
remain 512 MiB / 1 GiB. Verification uses persistent disk rather than the 64 MiB
container /tmp. Pixel conversion and image quality settings were preserved.

Physical review tools are available, but artworks are not automatically marked
panel-approved. That status remains an owner assessment. Source bytes and
existing event dates, enabled settings, messages and assignments remain intact.
