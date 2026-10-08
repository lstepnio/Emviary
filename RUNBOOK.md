# Owner operations

Service: https://eink.majjix.com
Host: `lstepnio@one.majjix.com`
Compose service: `einkartifact`; container: `einkartifact`

## Routine checks

```sh
ssh lstepnio@one.majjix.com
cd /docker
docker compose ps einkartifact
docker exec einkartifact einkartifact status
docker logs --tail 50 einkartifact
```

`client_etag` matching `served_etag` on a later device request is evidence that
PhotoFrame accepted the previous image. Physical panel inspection remains the
final check. USB operation does not validate deep sleep or battery endurance.

## Add another E1002

```sh
docker exec einkartifact einkartifact add-frame another-frame \
  --token-file /data/provisioning/another-frame.token
docker exec einkartifact einkartifact prepare another-frame
docker exec einkartifact einkartifact provision another-frame \
  --token-file /data/provisioning/another-frame.token \
  --output /data/provisioning/another-frame.json
```

The files are owner-readable secrets. Transfer the JSON privately and submit it
to the device's local `POST /api/config`; do not paste it into Git, tickets or
chat. The device must be awake. Setting the HTTPS image URL pins the server
certificate; confirm `ca_cert_set` and a successful `POST /api/rotate` afterward.
Each frame has a separate bearer token; the database stores only its hash.

## Change wake time or appearance

```sh
docker exec einkartifact einkartifact set-frame gift-e1002 --wake 03:15
docker exec einkartifact einkartifact set-frame gift-e1002 --labels on --weather-cues on
docker exec einkartifact einkartifact prepare gift-e1002
```

Configuration is delivered on the next request. Changes to the wake schedule
use a new ETag even when image bytes are unchanged, because firmware skips
configuration on a 304 response. Keep preparation earlier than wake time.
An appearance change prepares a new profile. `prepare --force` deliberately
creates another selection; routine retries reuse the persisted plan.

## Backup and recovery

Nightly at 03:00 local time the application backs up SQLite through its online
backup API, the site config, artwork/credits, and each active image. Seven daily
backups live in `/docker/backups/einkartifact`. Image history is kept for 30 days,
provider snapshots for 14 days, and the active last-good image is kept regardless
of age. Raw token/provisioning files are excluded from application backups.

```sh
docker exec einkartifact einkartifact backup
```

A `COMPLETE` marker is written after integrity validation and copying. These
host-local backups still need an independent host backup to survive disk loss.

For restore, stop only this service. Preserve the current data directory, restore
the backup SQLite as `/docker/appdata/einkartifact/data/einkartifact.sqlite3`,
copy `active-cache/*` into `data/cache/`, and restore `site.json` and `art/` to
those bind mounts. Remove old WAL/SHM files only from the restored directory,
with the service stopped. Maintain UID/GID 1000. Start the service and verify
health, status, authenticated image retrieval and a device refresh. The restored
hashes recognize existing device tokens; lost owner plaintext files require
rotation and reprovisioning.

## Token rotation

```sh
docker exec einkartifact einkartifact rotate-token gift-e1002 \
  --token-file /data/provisioning/gift-e1002-new.token
```

Rotation invalidates the old token immediately. Provision the awake device with
the new token using a new output filename, then test refresh before gifting.

## Releases

Build on the amd64 host from the private application repository. Use a new image
tag, back up first, update only the `einkartifact` image in Compose, validate
`docker compose config --quiet`, then `docker compose up -d --no-deps einkartifact`.
The pinned base images and lockfiles make dependencies explicit. Do not run the
host's whole-stack upgrade or backup script just to release this application.
`pull_policy: never` keeps routine stack pulls from looking for our local image
on Docker Hub. A prior image rollback does not undo a database schema migration.

The host config-export script includes only site config, release metadata,
catalog and credits for this service. SQLite, tokens, and provisioning files
stay out of that export. Firmware remains pinned separately in `firmware.lock.json`.
