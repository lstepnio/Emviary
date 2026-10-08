# Owner operations

Service: https://emviary.majjix.com
Host: `lstepnio@one.majjix.com`
Compose service: `emviary`; container: `emviary`

## Management

Open https://emviary.majjix.com/manage and sign in with the private owner password.
The dashboard manages frame schedules, one-to-three-bird layouts, selection constraints,
labels, season/forecast cues, local coordinates/radius, provider settings, eBird
credentials, frame provisioning and password changes. Settings are validated and
persisted in SQLite; no Docker rebuild is needed. An owner preview can differ
from the public mirror until the sleeping device retrieves its next image.

The bootstrap password is in the private host file
`/docker/appdata/emviary/data/provisioning/owner-login.txt` (0600).
Change it through management. `init-owner` bootstraps a previously uninitialized
installation and refuses to replace an existing owner password. Keep the mounted `/run/secrets` directory private and writable by UID 1000 so
management can replace password hashes and provider credentials.

The public root mirrors the selected frame's last delivered image. This is based
on firmware fetch telemetry, not direct panel sensing. Choose the public frame
in management or hide it. The source-art library is at `/library`.

The local-controls link opens http://emviary.local, with http://photoframe.local as a fallback. It works on the frame's
local network while the device is awake; it does not wake the sleeping device.

Expand **Special days** on a frame to add, edit, disable or remove an occasion.
Set the calendar date, annual recurrence or one-time occurrence, heading,
optional greeting, artwork theme and optional featured bird illustration.
Headings allow 40 characters and greetings 80. Selected art must be approved
and seasonally eligible in that month. The occasion uses one bird for readable
messaging, regardless of the normal maximum. The first enabled matching entry
wins; annual February 29 events run only in leap years.

**Preview this day** renders the next annual occurrence, or the exact one-time
date, without changing the ready image or public mirror. Previews omit a
forecast because they do not query future weather. If adding an occasion for
today, use **Prepare a fresh composition** after saving so it is ready for the
next wake. Otherwise nightly preparation handles it automatically. The next
day returns to normal bird rotation. No extra wakes or firmware changes are
needed. Personal occasion settings are available only in authenticated
management; the greeting is visible on the public mirror once delivered.

The CLI below is retained for recovery and administration.

## Routine checks

```sh
ssh lstepnio@one.majjix.com
cd /docker
docker compose ps emviary
docker exec emviary emviary status
docker logs --tail 50 emviary
```

`client_etag` matching `served_etag` on a later device request is evidence that
PhotoFrame accepted the previous image. Physical panel inspection remains the
final check. USB operation does not validate deep sleep or battery endurance.

## Physical buttons

The Emviary E1002 firmware disables the right-hand button entirely: it does
not clear the panel or wake the sleeping frame. Green wakes Wi-Fi/local management
and resets the awake sleep timer. Left fetches the backend's prepared image; if
asleep, it wakes, fetches and returns to sleep. A matching ETag skips repainting.
Left does not request a new backend art selection. Green alone does not refresh.

## Add another E1002

```sh
docker exec emviary emviary add-frame another-frame \
  --token-file /data/provisioning/another-frame.token
docker exec emviary emviary prepare another-frame
docker exec emviary emviary provision another-frame \
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
docker exec emviary emviary set-frame emily-e1002 --wake 03:15
docker exec emviary emviary set-frame emily-e1002 --labels on --weather-cues on
docker exec emviary emviary prepare emily-e1002
```

Configuration is delivered on the next request. Changes to the wake schedule
use a new ETag even when image bytes are unchanged, because firmware skips
configuration on a 304 response. Keep preparation earlier than wake time.
An appearance change prepares a new profile. `prepare --force` deliberately
creates another selection; routine retries reuse the persisted plan.

## Backup and recovery

Nightly at 03:00 local time the application backs up SQLite through its online
backup API, the site config, artwork/credits, and both active and last-delivered images. Seven daily
backups live in `/docker/backups/emviary`. Image history is kept for 30 days,
provider snapshots for 14 days, and the active last-good image is kept regardless
of age. Last-delivered images are also protected while a newer image waits
for a sleeping device. Raw token/provisioning files are excluded from application backups.

```sh
docker exec emviary emviary backup
```

A `COMPLETE` marker is written after integrity validation and copying. These
host-local backups still need an independent host backup to survive disk loss.

For restore, stop only this service. Preserve the current data directory, restore
the backup SQLite as `/docker/appdata/emviary/data/emviary.sqlite3`,
copy `active-cache/*` into `data/cache/`, copy backup `event-art/` into
`data/event-art/`, and restore `site.json` and `art/` to those bind mounts.
The cache backup now includes retained navigable images, and the SQLite backup
includes render counts, event schedules, refill jobs and battery history. Remove old WAL/SHM files only from the restored directory,
with the service stopped. Maintain UID/GID 1000. Start the service and verify
health, status, authenticated image retrieval and a device refresh. The restored
hashes recognize existing device tokens; lost owner plaintext files require
rotation and reprovisioning.

## Token rotation

```sh
docker exec emviary emviary rotate-token emily-e1002 \
  --token-file /data/provisioning/emily-e1002-new.token
```

Rotation invalidates the old token immediately. Provision the awake device with
the new token using a new output filename, then test refresh before gifting.

## Releases

Build on the amd64 host from the public application repository. Use a new image
tag, back up first, update only the `emviary` image in Compose, validate
`docker compose config --quiet`, then `docker compose up -d --no-deps emviary`.
The pinned base images and lockfiles make dependencies explicit. Do not run the
host's whole-stack upgrade or backup script just to release this application.
`pull_policy: never` keeps routine stack pulls from looking for our local image
on Docker Hub. A prior image rollback does not undo a database schema migration.

The host config-export script includes only site config, release metadata,
catalog and credits for this service. SQLite, tokens, and provisioning files
stay out of that export. Firmware remains pinned separately in `firmware.lock.json`.

## eBird secret

The key lives at `/docker/appdata/emviary/secrets/ebird-api-key` with mode
0600, owner 1000, in a 0700 directory. Management replaces this secret atomically;
the container mounts the secret directory writable for this purpose.
No container rebuild is needed. The API token is sent in `X-eBirdApiToken`, never
in the URL. Management enables the adapter and sets the lookback window and
shared locality radius. The POC caps recent eBird results at 100 species. Missing credentials or an API failure fall
back to other evidence and the curated library. Back up credentials separately
in a private secret store; application backups deliberately exclude them.

## Statewide bird selection

Management offers Near the weather location or All Colorado. Colorado uses eBird
region `US-CO` and Colorado bounds for BirdWeather, without changing the Denver
weather coordinates, timezone or wake schedule. The local radius is ignored in
statewide mode. Scope changes invalidate cached bird evidence. Queries remain
bounded to 100 BirdWeather stations, 32 top species and the configured eBird
result limit; this is regional evidence, not an exhaustive state inventory.
Only available approved, seasonally eligible artwork participates in rotation.

## Firmware updates

The default frame policy takes any newer compatible published release, including
prereleases. In management, expand Firmware updates to pause updates or specify
a version. A pin permits an upgrade to that exact published version; it does not
force a downgrade. Automatic without a pin resumes the newest compatible release.
The frame requests `/v1/firmware` with its existing bearer token every online
wake. Failed discovery, downloads or digest validation retain its current
firmware and artwork. A check never counts as picture delivery.

Publish from the Emviary-firmware repository's Emviary E1002 workflow with a
semantic release tag, or push a `v*` tag. Builds use ESP-IDF v6.0 and publish only
a successful E1002 binary plus SHA256SUMS and firmware-manifest.json. Releases
are immutable; use a new version for each change. Branch CI builds alone do not
publish firmware. The GitHub release API is cached for ten minutes in the
backend; frames download the binary directly from GitHub.

Local controls: `http://emviary.local`, with `http://photoframe.local` as a fallback
while the frame is awake on the same Wi-Fi. The primary frame is `emily-e1002`.

## Stage Wi-Fi before gifting

Wake the frame on its current Wi-Fi, then sign in to cloud management and open
**Saved Wi-Fi networks** for `emily-e1002`. Add the destination's 2.4 GHz SSID
and password. A blank password retains a previously saved password; select Open
network explicitly for an unprotected network. Credentials are stored privately
and are never shown again in management, status, or the public display.

On the next online image fetch, firmware v0.4.0 merges cloud networks ahead of
existing staging/recovery networks. Keep no more than five total networks. Wake
and refresh before gifting, then check the saved list in the awake frame's local
Settings. This confirms delivery without requiring the destination router nearby.
Cloud removal forgets that cloud-managed SSID; the firmware refuses to delete its
final network. Device-only networks can be removed or reordered locally.

Local Settings also supports saved networks directly without an immediate
reconnect. A blank password retains that SSID's saved credential. Networks are
selected on the next wake, with visible networks tried first in saved order.
Use DHCP when moving between locations. Enterprise Wi-Fi and sign-in portals
are outside this feature. Test connectivity at the destination before relying
on unattended overnight operation.

## Recipient recovery guide

Authenticated management includes a frame recovery section and a per-frame
**Download recovery import file** link. The installed Emviary firmware still
uses `PhotoFrame - XXXXX` for its open setup hotspot; connect to it and open
`http://192.168.4.1/provision`. An ordinary reboot retains settings and does not
force a setup hotspot. Factory reset erases NVS, including Wi-Fi and the cloud
token, but retains firmware. Restore Wi-Fi first, then import the recovery file
under local Settings → Maintenance → Config Backup.

The recovery download uses the webapp's `{"config": {...}}` format and omits
Wi-Fi fields so it cannot replace the network just used to recover. The legacy
flat provisioning download remains unchanged. Both are authenticated and sent
with `Cache-Control: no-store`; the embedded frame token must be kept private.

## Holiday and season artwork

Use **Add a collection** under a frame’s Special days to import US holidays or
meteorological seasons. New presets start disabled. Existing customized events
are preserved, and repeated imports do not duplicate them. Fixed-date events
repeat annually; movable holidays apply to the selected year. Import next year
when needed. Meteorological seasons start March 1, June 1, September 1 and
December 1. Edit dates and disable annual repeat for an exact local equinox or
solstice in a chosen year.

Open `/manage/event-art` to upload PNG, JPEG or WebP art with a title and creator
or source. Review and approve the art before selecting it for an event. Occasion
art can be a landscape, abstract design, photograph or other nonbird image and
never joins ordinary bird rotation. Assign the image, greeting and date, then
enable the event. Preview it before use. Artwork selected by an event must be
unassigned before it can be removed or returned to review.

## Battery history and charging alerts

Open `/manage/battery` for percentage history, voltage, charging/USB state and
conservative estimates of days until 20%. Owner management shows a charge alert
at 20% or an estimated crossing within seven days. Alerts stay in management;
no email or webhook is configured. Firmware v0.6.0 supplies power-state headers.
Older readings remain visible but are excluded from estimates when their power
source is unknown. Percentage is derived from battery voltage and can fluctuate.

Samples are deduplicated within 15-minute buckets and kept for one year. A
forecast requires at least five daily readings spanning seven days and a
five-point drop in one discharge cycle. Charging or a significant upward jump
starts a new cycle. Stale, flat or noisy readings suppress estimates. Battery
life is not yet established; use a complete battery-powered cycle to assess it.

Firmware v0.6.0 uses internal LittleFS and disables SD albums and SD `wifi.txt`
provisioning in this Emviary E1002 profile. Green-button web recovery, config
imports, Wi-Fi networks, image downloads, OTA and the 03:15 schedule remain.
