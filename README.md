# eInkArtifact

A Denver-area bird-art gift built around the reTerminal E1002.

A sleeping ESP32 PhotoFrame client retrieves one prepared image each night from
https://eink.majjix.com. One Python Docker service on `one.majjix.com` combines
curated Fugleramme bird illustrations, regional BirdWeather detections and optional eBird observations, seasonal
motifs and understated Open-Meteo forecast cues. No paid subscription, microphone,
Raspberry Pi or online image generation is required for this POC.

## Implementation

- Eight species, eleven curated poses; source links and CC BY-SA credits retained.
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
- One or two distinct birds, sized for the 800×480 panel, with sparse seasonal
  edges and forecast cues behind the unchanged curated illustrations.
- Health check, restricted container and existing Caddy integration.

The firmware fork is https://github.com/lstepnio/einkartifact-firmware, pinned to
upstream v2.19.0 with a small clear-screen recovery patch. It invalidates the
image cache marker when the panel is cleared and avoids a duplicate Spectra
refresh. The attached E1002 runs `dev-a514a2c`; its restored bird picture was
physically confirmed. Battery sleep and endurance need separate validation.
See [research/DISPLAY_DIAGNOSTICS.md](research/DISPLAY_DIAGNOSTICS.md).

## Local development

```sh
git clone --recurse-submodules git@github.com:lstepnio/eInkArtifact.git
cd eInkArtifact
uv sync --locked
npm ci --ignore-scripts --prefix converter
npm run install --prefix converter/node_modules/canvas
uv run einkartifact add-frame local-e1002 --token-file .state/provisioning/local-e1002.token
uv run einkartifact prepare local-e1002 --offline
uv run einkartifact serve
```

The default configuration is `deployment/site.example.json`. Set `EINK_CONFIG`,
`EINK_DATA_DIR`, `EINK_ART_DIR`, and `EINK_BACKUP_DIR` to override paths. All owner
provisioning files are secrets and excluded from Git. The public homepage shows
the selected frame's latest delivered art with a subtle management link.
`/manage` requires the owner password; `/library` shows source artwork and credits.
`/v1/image` and `/v1/preview` require the frame's bearer token. The panel preview
is decoded from the exact packed pixels; perceived physical colors vary with
lighting. Delivery telemetry is not a physical panel acknowledgement.

For local management, set `EINK_SECRET_DIR` to a private writable directory and
run `einkartifact init-owner --password-file .state/provisioning/owner-login.txt`.
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

Original service code is MIT licensed. Curated artwork and new compositions are
CC BY-SA 4.0; fonts are OFL licensed. Artwork provenance is in
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
Observations outside that circle are filtered before selection. The eight
curated species are Denver residents; this POC varies seasonal surroundings
rather than claiming a complete migratory bird catalogue. Additional species
require reviewed, licensed art and locality/season metadata.
