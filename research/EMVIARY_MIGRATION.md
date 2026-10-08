# Emviary migration

Emviary is the new name for the former eInkArtifact project.

- Canonical service: https://emviary.majjix.com.
- Application repository: https://github.com/lstepnio/Emviary.
- Firmware repository: https://github.com/lstepnio/Emviary-firmware,
  branch `emviary-poc`. The tested installed firmware revision remains pinned
  in `firmware.lock.json`; `branding_commit` records the renamed future build.
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
