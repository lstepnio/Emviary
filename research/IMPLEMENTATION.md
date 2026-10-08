# Implemented POC, 2026-10-08

The private application repository is `lstepnio/eInkArtifact`. Its application
release is commit `b355019`, version 0.2.0, deployed as `einkartifact:poc-003` on
`one.majjix.com`. Docker image ID:
`sha256:f0e43408350f9ab720dc98af8f1ef7cca9d7a71d1f3fdee22ad7b8ba594f852d`.
The non-secret host release manifest is in the service's config directory.

## Verified

- HTTPS public root displays the selected frame's last delivered art. The subtle
  management link opens a password sign-in page. Preparing an upcoming image
  does not replace the public mirror before firmware retrieval.
- Owner sign-in, protected dashboard, CSRF rejection, setting persistence across
  container replacement, and secret omission from dashboard responses passed
  against the deployed service. The bootstrap password was delivered as a
  private local file, not included in this repository.
- eBird is enabled through management. Live normalized evidence included 100
  recent species from eBird and 32 BirdWeather species from 64 stations within
  the configured Denver locality. Open-Meteo returned the dated local forecast.
  Provider counts are evidence inputs, not population estimates.
- The final prepared image has two distinct species: House Finch and Black-capped
  Chickadee. Its packed output has the required 192,000 bytes; all 320,688 exactly
  white source pixels use white ink. The current physical display retains the
  previously delivered Chickadee composition until its next request.
- The service is healthy, idle memory was about 52 MiB and CPU below one percent.
  Only this Compose service was recreated; the existing 21-container inventory
  remained present. SQLite integrity check returned `ok`.
- Configuration/Compose backups preceded releases. An application backup at
  `/docker/backups/einkartifact/owner-ui-poc003-20261008` includes effective config,
  database, attribution/art and active plus last-delivered images. Secrets and
  raw provisioning files are excluded. Backups remain on the same host.
- Twenty backend tests, formatting and lint passed. Application CI:
  https://github.com/lstepnio/eInkArtifact/actions/runs/37781226592
- Firmware build and flash details are in `DISPLAY_DIAGNOSTICS.md`. The patched
  firmware is `a514a2c`, physically restored art was confirmed stable, and an
  unchanged request skipped panel refresh. Firmware CI:
  https://github.com/lstepnio/einkartifact-firmware/actions/runs/37744229866

## Remaining physical validation

The frame is unplugged and sleeping; the owner reported that state. The nightly
wake remains 03:15 America/Denver, with backend preparation at 02:30. The original
blanking trigger is still unconfirmed. Overnight picture retention, unattended
nightly refresh and three-month battery endurance have not yet been established.
Temporary firmware debug logging remains enabled to capture future wake/clear
behavior; turn it off after completing the hardware investigation.

The new two-bird composition is prepared and visible to the owner in management,
but has not been physically approved on this panel. Future AI art is disabled.
