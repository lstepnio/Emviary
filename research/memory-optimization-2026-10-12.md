# Memory optimization, 2026-10-12

## Change

Application 0.9.4 limits thumbnail cache misses to two simultaneous full-artwork
decodes. Thumbnail JPEGs persist under `/data/cache/thumbnails`; keys include the
encoding recipe, source path, nanosecond modification time and file size. Writes
use a temporary file and atomic rename, and failed jobs release the slot and
remove partial files. Hits stream files with byte-derived ETags, including HTTP
304 support, without decoding artwork or retaining a process-wide JPEG cache.
The single application worker remains unchanged.

Thumbnail and frame-rendering image buffers use explicit `Image.close()` through
`contextlib.closing`, including exception paths. Pillow image context managers
alone do not guarantee release of decoded pixel buffers. Masters, resizing,
alpha compositing, EXIF handling, JPEG quality, panel palette, dithering and
layout settings are unchanged. The Docker RAM limit remains 512 MiB and the
combined RAM-plus-swap limit remains 1 GiB.

## Validation before deployment

All 122 backend tests and lint passed. Tests cover the persistent cache across
application instances, source invalidation, conditional delivery, a two-job
concurrency bound, failed-write cleanup and original JPEG byte compatibility.

Isolated Linux containers used the existing production image and dependencies,
one CPU, a 512 MiB RAM limit, no swap, and read-only production artwork. Only the
candidate source differed. Eight requests selected the same eight largest
masters. Peak process RSS (not Docker container usage):

| Workload | Before | After |
|---|---:|---:|
| Eight concurrent cold thumbnail requests | 299.2 MiB | 162.3 MiB |
| Same requests after a fresh process starts with persisted disk cache | 299.2 MiB (no persistent cache) | 44.8 MiB |

Cold request peaks fell 45.8%; persisted-cache fresh-process peaks fell 85.0%.
These are controlled samples, not long-term production guarantees. Cold timings
were 2.13 s before and 2.69 s after; cached requests took 0.01 s. The concurrency
bound trades some cold-generation throughput for a lower peak.

All 214 source thumbnail JPEG fingerprints and 12 frame-master PNG fingerprints
(one, two and three birds in January, April, July and October) matched exactly.
Baseline fingerprints were generated before edits using `emviary:poc-034`.
Original artwork was mounted read-only throughout. Comparison artifacts remain
in the private deployment/benchmark workspace, not in the public art catalog.

Production at task start reported 330.2 MiB, with its existing 512 MiB limit.
This warm, two-day-old process is not directly comparable to a freshly restarted
service; deployment snapshots are reported separately from controlled peaks.
