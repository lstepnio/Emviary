# Upstream projects and reuse

## ESP32 PhotoFrame

https://github.com/aitjcize/esp32-photoframe is the firmware base. Our fork is
https://github.com/lstepnio/einkartifact-firmware, branch `einkartifact-poc`, pinned
to v2.19.0 (`186ebaf3b470305824d238c2d2dabf2c5bc59a7a`). The E1002 already runs this
version. URL polling, bearer authentication, ETag caching, server configuration
headers, scheduled wake, and deep sleep provide the needed protocol without
custom firmware changes. The submodule retains upstream licensing.

## Fugleramme

https://github.com/arnegiacomo/fugleramme at
`62202503ddd059875367046d472d564840cd9cc6` supplies 11 curated cutouts covering eight
Denver-area species. We retain source plate links, asset hashes, restoration
credits, the collection's CC BY-SA 4.0 attribution, and the font's OFL license.
The importer copies source artwork unchanged. New rendered compositions are
also CC BY-SA 4.0. See `art/FUGLERAMME-ATTRIBUTION.md` and `art/catalog.json`.

The yellow-shafted Northern Flicker plate was excluded from this Denver POC:
local red-shafted birds would make that illustration a poor default.

## Avian Visitors

Article: https://theodore.net/projects/AvianVisitors/
Source: https://github.com/Twarner491/AvianVisitors/tree/avian-visitors
Examined commit: `2f18a66676b85d9548cfcbca21d94a4aab88e17a`.

Useful ideas adopted independently:

- Select only species with available, reviewed artwork.
- Keep the art library offline and prepare images outside the frame's request.
- Bound public BirdWeather GraphQL responses and tolerate provider outages.
- Reduce count dominance with a sublinear weight. Counts reflect detections,
  not individual birds or a backyard census.

Its collage packing, dual poses, station-specific selection, and eBird fallback
are useful future options. We defer them: a single bird reads better on this
800×480 panel, and regional data needs no microphone installation. Its larger
Pi-driven display and frequent updates do not match our battery-first goal.
Generated poses would require anatomical review before joining our catalog.

No Avian Visitors code or artwork was copied. The examined repository's root
license is CC BY-NC-SA 4.0; copying it would introduce obligations beyond our
own MIT service and the curated collection's CC BY-SA artwork.
