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
| Eight concurrent cold thumbnail requests | 299.2 MiB | 172.2 MiB |
| Same requests after a fresh process starts with persisted disk cache | 299.2 MiB (no persistent cache) | 44.0 MiB |

Cold request peaks fell 42.4%; persisted-cache fresh-process peaks fell 85.3%.
These are controlled samples, not long-term production guarantees. Cold timings
were 2.13 s before and 2.01 s after; cached requests took 0.01 s. The concurrency
bound limits peak load; timings are single samples and not throughput guarantees.

All 214 source thumbnail JPEG fingerprints and 12 frame-master PNG fingerprints
(one, two and three birds in January, April, July and October) matched exactly.
Baseline fingerprints were generated before edits using `emviary:poc-034`.
Original artwork was mounted read-only throughout. Comparison artifacts remain
in the private deployment/benchmark workspace, not in the public art catalog.

Production at task start reported 330.2 MiB, with its existing 512 MiB limit.
This warm, two-day-old process is not directly comparable to a freshly restarted
service; deployment snapshots are reported separately from controlled peaks.

## Deployment and final verification

The final `emviary:poc-035` image (application 0.9.4) is healthy. Its image ID is
`sha256:e0af768b8593038f3eaef9cda0c5a347e616833537a6c489c29ab99b73bab04f`;
application commit is `22ba347828271620eb81c147a211135ea99b8707`.
The table above uses final built-image measurements, with a fresh cache directory
for the cold run. The cold run recorded eight decodes; the fresh-process cached
run recorded zero. Candidate-source measurements were 162.3 MiB cold and
44.8 MiB cached, illustrating normal peak variation between individual runs.

Eight live HTTP thumbnail responses matched the pre-change JPEG fingerprints.
A real conversion of the three-bird autumn composition using the pinned Node
converter produced identical EPDGZ and panel-preview JPEG bytes before and after:

- EPDGZ SHA256: `2c6bd8196d053ca5989c49c37b52d60fff1131c5c55a2d612ded5f9623fcc8b6`
- Preview SHA256: `ac8d013db2d6b7cf6d1b0df17c35af96dc8727313735cad4972f8aad23ea9575`

After the deployment and live requests, Docker reported approximately 187 to
190 MiB, compared with 330.2 MiB at task start. No swap, limit events or OOM events
were recorded for the new container during these checks. These point-in-time
production readings include the effects of restart and workload variation; the
controlled benchmark is the evidence for the thumbnail improvements. The frame
firmware, masters, catalog, scheduled refresh and deployed memory limits were
not changed. Rollback assets, the consistent database backup and build log are
in `/docker/backups/emviary/release-poc-035`.

Disk thumbnails are regenerable cache data. A source or recipe change creates a
new immutable entry; old entries can be cleared during cache maintenance without
altering artwork or frame history. The cache is separate from active frame files.
