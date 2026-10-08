# Emviary migration

Emviary is the new name for the former eInkArtifact project.

- Canonical service: https://emviary.majjix.com.
- Application repository: https://github.com/lstepnio/Emviary.
- Firmware repository: https://github.com/lstepnio/Emviary-firmware,
  branch `emviary-poc`. Both repositories are public. The published firmware
  revision and complete application SHA256 are pinned in `firmware.lock.json`.
- Python package and CLI: `emviary`, version 0.3.0. Configuration variables
  use `EMVIARY_`. Docker image: `emviary:poc-010`.
- Compose service and container: `emviary`.
- Persistent application: `/docker/appdata/emviary`; backups:
  `/docker/backups/emviary`; database: `data/emviary.sqlite3`.
- Browser requests to the old hostname redirect to the new one. Its `/v1/`
  endpoints remain served directly, without redirects, because an installed
  frame may retain its old image URL. Future provisioning uses the new URL.
- Management passwords and frame tokens are preserved. Sign in again on the
  new hostname because secure session cookies are host-specific.
- Colorado bird scope, Denver weather, the three-bird cap, special days,
  prepared images, public delivery mirror and the 03:15 wake remain preserved.

Pre-migration application backup: `20261008T170001Z`, now under the renamed
backup directory. `rebrand-emviary` contains the previous Compose file,
source archive, configuration-export script and Git ignore rules. Historical
release records in other documents predate the rename: old image tags used
`einkartifact`, and old paths were under `appdata/einkartifact` and
`backups/einkartifact`. Commit IDs and image digests are unchanged by renaming.

Rollback requires stopping only `emviary`, restoring the old application and
backup directory names, restoring the pre-migration database and site config,
Compose and export script, and starting only `einkartifact`. Preserve current
state before restoration. Renaming only the image cannot undo the package,
environment, database-name and canonical-URL migration. The local-hostname follow-up installs a new firmware image with
`emviary.local` and a `photoframe.local` mDNS alias. The frame registry ID
is `emily-e1002`; existing token hashes, delivery state and image history
remain preserved.

The local checkout is `/Users/lukasz.stepniowski/Development/Emviary`; the
former checkout path is a compatibility symlink for existing tools.

The deployed application implementation is commit
`a30e86b45342a0560fcb1804c985ab81cd5ee11e`, image `emviary:poc-010`,
package 0.3.0, renderer 6. All 37 application tests and lint checks passed.

Firmware v0.3.3 is published by the E1002 GitHub workflow. Firmware metadata
is fetched on each online wake through the authenticated cloud endpoint.
Automatic updates are the default, including compatible prereleases; management
can disable updates or pin a version. Completed downloads must match the
release size and SHA256 before the next OTA partition is selected. Scheduled
artwork refresh happens before an update reboot.

The frame automatically updated from GitHub v0.3.0 to v0.3.1 and refreshed
through the canonical domain; the owner confirmed the physical picture was
visible and stable. Both local hostnames resolved to the physical frame.

Final hardware verification: the frame automatically installed GitHub v0.3.3,
verified the full release digest, rebooted into v0.3.3, and confirmed no newer
update was offered. Serial logs confirmed both mDNS hostnames registered.
