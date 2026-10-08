# eInkArtifact

A Denver-area bird-art gift built around the reTerminal E1002.

A sleeping ESP32 PhotoFrame client retrieves one prepared image each night from
https://eink.majjix.com. One Python Docker service on `one.majjix.com` combines
curated Fugleramme bird illustrations, regional BirdWeather detections, seasonal
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
- Owner CLI, health check, restricted container and existing Caddy integration.

The firmware fork is https://github.com/lstepnio/einkartifact-firmware, pinned to
upstream v2.19.0. No custom firmware code is needed for the initial protocol.
The attached E1002 already runs that version. Physical display, unplugged wake
and battery endurance must be assessed separately from service tests.

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
curated source art and attribution; `/v1/image` and `/v1/preview` require the
frame's bearer token. There is no public owner dashboard.

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
