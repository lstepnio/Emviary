# Management simplification and USB recovery

October 12, 2026. Application 0.13.0.

The owner interface has seven destinations: Overview, Appearance, Special days,
Artwork library, Device health, Settings and Recovery. Device health belongs to
Setup & health; Artwork library is the only Collection destination.

Special days now contains both calendar editors and an expandable Artwork
collection near the top. Uploads are validated and automatically ready for
assignment. Assigned-art links open the relevant event editor; removal is blocked
while any frame uses the artwork. Upload/remove actions return to this same panel,
retain frame context and expand Artwork collection. Pending legacy uploads become
ready once, without changing artwork bytes, attribution or event enablement.

Removed the Birds to include UI, species-selection submit processing and browser
handlers. Existing saved species restrictions remain intact because they are a
backend selection input, not UI code. Rotation remains controllable from Artwork
library. Removed panel-review fields, filters, handlers, table creation and store
methods. Existing database tables are left inert instead of destructively migrated.
Removed web Frame history and its hide/restore endpoints; queued preview endpoints,
retention and backend history stay because physical previous/next navigation needs them.
Old history bookmarks redirect to Overview; old art bookmarks redirect to Special days.

Recovery adds a self-hosted laptop USB installer with explicit model confirmation,
verified immutable firmware parts, preservation by default, optional full erase,
progress, error handling and subsequent Wi-Fi/cloud import guidance. There is no
server USB process and no new frame polling. The default-off cloud debug switch
rides the existing image-fetch configuration response. See the [USB recovery
implementation](../web-recovery/README.md) for geometry, provenance and test limits.

Both public and management artwork galleries progressively append 24-card batches. Read-only gallery loads
reuse authenticated routes and existing bounded thumbnails. A failed load pauses
automatic retries, keeps cards and offers explicit retry. Actions reload the loaded
range, retain selections and preserve a card scroll anchor. Native pagination is
kept as the no-JavaScript fallback.

Trusted WAN access is per-frame opt-in, based only on a recent authenticated image
fetch and global source IP, with an explicit Caddy-only proxy allowlist. It grants
owner management to all users sharing the public IP. Each request is revalidated;
no portable session cookie is issued. Password changes still require password
sign-in. New frames default to password access. The E1002's existing frame will
be enabled under this request, taking effect after its next authenticated fetch.

Firmware v0.8.3 makes logging opt-in and removes E1002 flash core dumps. Five-second
LEFT hold renders a local snapshot without Wi-Fi on a hold-to-wake; short LEFT
remains previous, RIGHT next, and green restores artwork. Transient RAM and RTC
state avoid diagnostic flash writes. Cold reset also restores saved artwork so
an erased RTC overlay marker cannot leave a diagnostic screen stuck after a 304.
Actual hardware behavior and energy savings require separate physical verification.

Local acceptance: 231 Python tests, six browser-recovery JavaScript tests, Ruff checks, and JavaScript syntax validation passed. Management browser tests covered incremental loading through four batches, preserved selection and scroll after excluding a card, and 390 CSS-pixel layouts without horizontal overflow. The public gallery automatically reached all 63 species in three batches with no duplicate cards. The wheel includes all four verified v0.8.3 recovery binaries. Deployment acceptance follows below.

The firmware publication race produced immutable v0.8.2 before the final timestamp-write
optimization. It was preserved; final recovery and the firmware lock use v0.8.3.

The application can receive v0.8.3 through ordinary OTA with its approved existing rollback bootloader. OTA retains bootloader console output; the new silent bootloader requires USB recovery. ROM startup messages may still appear. No new physical firmware installation or browser USB flash is claimed by these software checks.
