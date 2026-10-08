# Emviary

A Colorado bird-art gift built around the reTerminal E1002.

A sleeping ESP32 PhotoFrame client retrieves one prepared image each night from
https://emviary.majjix.com. One Python Docker service on `one.majjix.com` combines
curated historical and existing illustrated bird art, regional BirdWeather detections and optional eBird observations, seasonal
motifs and understated Open-Meteo forecast cues. No paid subscription, microphone,
Raspberry Pi or online image generation is required for this POC.

## Implementation

- 62 Colorado species, 143 rotation images, three web-only field studies and two review candidates; original masters,
  source credits and per-asset provenance retained.
- 800×480 Spectra6 conversion through pinned `epaper-image-convert`, producing
  validated EPDGZ files. Rendering happens before the frame fetches.
- Preparation at 02:30 and frame wake at 03:15 America/Denver, including DST.
- Individual bearer tokens, saved configuration headers and ETag caching.
- SQLite registry and persisted jobs; retries reuse the chosen art and inputs.
- Provider outages retain the last good image; stale forecasts are omitted.
- Thirty-day image history, fourteen-day provider snapshots, seven daily
  consistent database/art/config backups; active images survive retention.
- Authenticated management for location, sources, bird selection, appearance,
  refresh schedule, frame provisioning and owner credentials.
- Public homepage mirrors the last image delivered to the selected frame;
  owner previews show upcoming prepared art separately.
- One to three distinct birds, default maximum three, sized for the 800×480 panel, with sparse seasonal
  edges and forecast cues behind the unchanged curated illustrations.
- Special dates with annual/one-time recurrence, custom greetings, four drawn
  occasion themes, chosen bird art and private previews. Local frame controls
  are linked from management.
- Health check, restricted container and existing Caddy integration.

The public firmware fork is https://github.com/lstepnio/Emviary-firmware, based
on upstream v2.19.0. It retains the safe panel refresh with clearing removed from the white buttons,
advertises `emviary.local` plus `photoframe.local`, and checks the authenticated
cloud update policy on every online wake. GitHub hosts immutable, board-specific
releases; complete-image SHA-256 verification precedes the OTA boot switch.
Automatic updates, including prereleases, are enabled by default; management
can pause updates or select a pinned version. Battery endurance still needs
separate validation.
See [research/DISPLAY_DIAGNOSTICS.md](research/DISPLAY_DIAGNOSTICS.md).

## Local development

```sh
git clone --recurse-submodules git@github.com:lstepnio/Emviary.git
cd Emviary
uv sync --locked
npm ci --ignore-scripts --prefix converter
npm run install --prefix converter/node_modules/canvas
uv run emviary add-frame local-e1002 --token-file .state/provisioning/local-e1002.token
uv run emviary prepare local-e1002 --offline
uv run emviary serve
```

The default configuration is `deployment/site.example.json`. Set `EMVIARY_CONFIG`,
`EMVIARY_DATA_DIR`, `EMVIARY_ART_DIR`, and `EMVIARY_BACKUP_DIR` to override paths. All owner
provisioning files are secrets and excluded from Git. The public homepage shows
the selected frame's latest delivered art with a subtle management link.
`/manage` requires the owner password; `/library` shows source artwork and credits.
`/v1/image` and `/v1/preview` require the frame's bearer token. The panel preview
is decoded from the exact packed pixels; perceived physical colors vary with
lighting. Delivery telemetry is not a physical panel acknowledgement.

For local management, set `EMVIARY_SECRET_DIR` to a private writable directory and
run `emviary init-owner --password-file .state/provisioning/owner-login.txt`.
Production bootstrap credentials are delivered privately, never committed.

```sh
uv run ruff check src tests tools
uv run ruff format --check src tests tools
uv run pytest -q
```

See [RUNBOOK.md](RUNBOOK.md) for owner operations and restore instructions,
[DEPLOYMENT.md](DEPLOYMENT.md) for the deployment specification,
[PLAN.md](PLAN.md) for architecture, cost and power tradeoffs, and
[research/PROJECTS.md](research/PROJECTS.md) for upstream reuse decisions.

Original service code is MIT licensed. Artwork retains its per-asset MIT,
CC BY-SA, CC BY-NC-SA or public-domain provenance; fonts are OFL licensed. Artwork provenance is in
[art/FUGLERAMME-ATTRIBUTION.md](art/FUGLERAMME-ATTRIBUTION.md) and
[art/catalog.json](art/catalog.json). Unreviewed generated experiments are kept
separately and excluded from runtime and deployment.

The deployed eBird adapter uses a secret file mounted at `/run/secrets/ebird-api-key`.
It queries recent reports within 25 km, limits responses to 100 species, and uses
reported presence as a selection bonus rather than mixing observation counts
with acoustic detections. The key and observer/checklist details are not stored
in snapshots, artwork manifests, Git or application backups. Enable it per site
in management; the example keeps it disabled for local setup. BirdWeather and
eBird share the configured center and locality radius, defaulting to 25 km.
Observations outside that circle are filtered before selection. The expanded
catalogue includes Denver-area residents and seasonal birds, with eligibility
windows attached to the art, including breeding-plumage restrictions. It does
not claim to be a complete bird catalogue. See
[research/RELATED_PROJECTS.md](research/RELATED_PROJECTS.md) for the five-project
review, incorporated artwork, validation and prioritized feature ideas.

Emviary was previously named eInkArtifact. Both application and firmware repositories are public; operational secrets and
device provisioning files stay outside Git.
See [migration notes](research/EMVIARY_MIGRATION.md) for compatibility and rollback.

### Species captions

The frame displays common bird names only. Scientific names remain in the web library, source credits and backend species matching. Removing the second caption row increases the main artwork region by 36 pixels in height, with 18 extra pixels for special-day bird art. Common names can still wrap onto two lines for multi-bird compositions.

### Display header

Enable **Show location name** in frame management to include the area name (currently Colorado) in the upper-left corner, without a date. This option defaults to off for new frames; it is enabled for Emily’s frame. Legacy location/date settings remain readable and now control the name only. This only changes the artwork; locality selection, forecast date validation and the nightly wake schedule continue to use the configured location and date.

### Daily weather on the artwork

The compact header summarizes the prevailing daylight sky for the dated Denver forecast, rather than the worst cloud condition across all 24 hours. Daily rain, snow, storm and wind cues take precedence. It is a forecast, not a live observation. High / low temperatures appear beneath the word in Fahrenheit by default; turn them off with **High / low beneath forecast (°F)** in frame management. The high and low cover the full local calendar day. Existing frames receive this default without firmware changes. Weather snapshots are tied to the requested date and location; older dates never supply weather cues.

### A picture ready for the next wake

After a firmware image download completes, the backend prepares one new image in the background. The right white button advances to the next saved composition and the left white button returns to the previous one (firmware v0.5.0+), while the automatic 03:15 refresh remains unchanged. Allow a few seconds between wakes for rendering. The public display continues to mirror the image last delivered to the frame; management previews show the prepared next image.

Preview requests do not advance the rotation. Duplicate downloads share one refill, and the persistent queue survives server restarts. Failed renders keep the last good image and retry every 15 minutes, up to three attempts per local day. Nightly preparation still supplies a fresh forecast for the new day. The refill queue works with existing firmware; bidirectional white-button navigation requires v0.5.0 or later.

Management includes an authenticated image-history gallery and artwork rotation controls. Removing a composition excludes it from navigation; the image currently displayed is protected until the frame advances. Excluding source artwork also replaces an upcoming composition that uses it. Neither operation removes attribution. Species render counters count each species once per successful composition, across all frames, and survive history removal/expiry. Existing saved history seeds the initial counters; already expired history cannot be reconstructed.

Weather appears on one header line. Icon, condition words and high/low temperatures each have an independent management toggle, enabled by default, under the master weather control. Date-mismatched forecasts remain omitted.
