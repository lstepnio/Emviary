# Related bird-frame projects: review and incorporated artwork

Reviewed 2026-10-08. This is an expansion of eInkArtifact's existing backend,
not a replacement firmware or an additional service on the recipient's network.
The E1002 still wakes nightly to fetch one prepared 800×480 Spectra6 artifact.

## What was incorporated

The rotation library grows from **11 images / 8 species** to **73 images / 32
species**, with three additional web-only reference plates. Masters are copied
unchanged, hashed and attributed. The backend preserves aspect ratio, composes
one or two birds, and applies the existing LAB/Spectra6 conversion and selected
dither. Text and neutral borders retain their black/white correction.

| Collection | Added to rotation | Treatment |
| --- | ---: | --- |
| HABirdDashboard / shared AvianVisitors collection | 56 cutouts, 28 species | Perched and flight poses; adds 20 species beyond the original eight. Existing upstream generated art, visibly labelled as such in the library. |
| Belkins birdnet | 4 cutouts, 2 species | Unique House Sparrow and Northern House Wren poses. |
| Featherframe's historical-bird-plates source | 2 plates, 2 species | Audubon's Wild Turkey and Bald Eagle. Each historical composition appears alone. |
| Inky Bird Frame | 0 panel / 3 web references | Original House Finch, Mourning Dove and Common Raven field-study plates with upstream review manifests. Dense text and paper texture are unsuitable for this small landscape panel. |
| BirdFrame regional pack | No duplicate imports | Three sampled Western US images are byte-identical to the selected HABirdDashboard raven, dove and goldfinch. Their shared distribution is recorded on those assets. |

The first 11 Fugleramme cutouts remain available. The three field studies cover
species already in rotation and therefore do not inflate the 32-species count.

### Curation decisions

- Reviewed candidate contact sheets for obvious anatomy, identity and silhouette
  problems. This was a visual screening, not an independent ornithologist's
  certification. Physical color/readability review of the new assets is pending.
- Left out the generated Northern Flicker and Bullock's Oriole variants because
  their field marks/geographic form need closer verification. The existing
  yellow-shafted historical flicker is still excluded from the Denver default.
- Bright breeding-male American Goldfinch images are eligible April-September,
  even though the species is resident. A muted winter variant is a useful next
  addition. This avoids using plumage as an incorrect seasonal signal.
- Broad-tailed Hummingbird, Barn Swallow and Northern House Wren art is eligible
  April-September; Mountain Bluebird March-October; Turkey Vulture March-October.
  Dark-eyed Junco is a conservative lowland winter default, October-April.
  These are curation windows, not exact arrival dates or population estimates.
- Retained year-round art for appropriate Denver/Front Range residents. The
  configured center/radius still limits provider evidence. A regionally eligible
  bird is never labelled as having visited this particular garden.
- The historical American Crow crop has substantial foliage and a small bird
  after scaling. The Harlan's hawk plate needs more geographic/form context and
  packs two detailed birds into a portrait crop. Neither was activated.
- No new online art generation was enabled. This expansion introduces no image
  API calls, microphone requirement or paid subscription.

Locality references: [Denver Audubon's common birds](https://www.denveraudubon.org/commonbirdsofdenver),
[Audubon Rockies' Denver habitats](https://www.audubon.org/rockies/news/where-find-birds-denver).
Form check: [Cornell's Northern Flicker identification](https://www.allaboutbirds.org/guide/Northern_Flicker/id).
These sources inform the curated defaults; ongoing provider reports supply
recent regional context rather than a comprehensive catalogue of occurrence.

## Findings by project and useful features

### Inky Bird Frame

[Repository](https://github.com/veteranbv/inky-bird-frame), inspected revision
`15eefcc2cdf1538a61f3653bd4cc8720641ede6b`.

A controller collects observations, researches species, creates field-journal
plates, independently reviews them, and serves an approved catalogue to the
frame. The reusable plate does not contain an owner's location. Asset hashes,
profile sources, model/prompt version and review findings are recorded. Its
`shuffle_bag` rotation covers each active species before repeating the cycle.
Provider adapters include eBird, BirdWeather and local BirdNET sources.

**Useful next features:** a persistent per-frame diversity cycle, a review queue
with documented rejection reasons, and source health notifications only when
there is a meaningful failure or change. If generation is added later, retain
its research-first and bounded-review workflow; never generate directly into
nightly rotation. Its portrait plates and rotated display files do not fit our
panel well. Borrowing the research model is more valuable than shrinking all
of that text onto the E1002.

### HABirdDashboard

[Repository](https://github.com/adamoberley/HABirdDashboard), inspected revision
`c52f4584134d437f57f6bddf0f3252f99b2c3cae`, default branch `HABirdDashboard`.

A Home Assistant/BirdNET-Go dashboard with a large illustration library, two
poses per many species, an atlas, detection statistics and detail cards with
recordings and reference calls. It can use existing camera RTSP audio instead
of installing a separate microphone. The UI lazy-loads art and pauses frequent
polling when hidden.

**Useful next features:** richer bird detail cards in our web library, a
perched/flight preference and favorite or blocked variants. Reference calls
belong on the web, not in the panel's sparse composition. The frequent live
updates and counts-based collage sizing are poor defaults for a battery frame.
We do not need Home Assistant just to reuse these images.

### Belkins birdnet

[Repository](https://github.com/Belkins/belkins-birdnet), inspected revision
`790c1557228b86fcc2d38853e96b7129a1c874f3`.

Combines BirdNET-Pi detection storage, generated illustration production and a
living bird collage. Its library overlaps heavily with HABirdDashboard:
**500 matching illustration paths, 494 byte-identical Git blobs** in the pinned
snapshots. Importing both entire repositories would mainly add duplicates.
Its unique local House Sparrow and House Wren poses provide actual diversity.

**Useful next features:** an optional local-detection adapter with a confidence
floor and deduplicated daily species summary. If a microphone is later added,
classify locally on the modern Pi and send a small summary to our service. Keep
raw audio local by default. Illustration generation should be a staged library
maintenance task with review, not a live response to each detection.

### Featherframe

[Repository](https://github.com/wr/featherframe), inspected revision
`0e06ea0333b3091018f70b01ec417f00dd31bef3`.

Matches BirdNET-Pi, BirdNET-Go or BirdWeather species to human-drawn Audubon and
Gould illustrations. Supports several screen families and server/cloud models.
Its region determines which historical folio is preferred; generated missing
species and daily collages are optional. Its associated
[historical-bird-plates](https://github.com/wr/historical-bird-plates) catalogue
maps old printed names to modern scientific names and eBird/BirdNET identifiers.
That mapping matters: an old plate title can identify a different modern bird.

**Useful next features:** an art-source/style preference, checked taxonomy
aliases and safe handling of historical multi-bird plates. For Denver, favor
Audubon's North American material rather than importing European or Australian
birds solely because a familiar printed name matches. Wider historical plates
make good single-art compositions; do not crop away birds to force them into a
collage. We use its historical source directly, not its firmware or generated
boot-screen decorations.

### BirdFrame

[Repository](https://github.com/simenf/birdframe), inspected revision
`de9c32e4ab4743f6313549821a15f6caa3fd8127`.

Docker-hosted bird detection and artwork experience with multiple layout
previews, setup guidance and downloadable regional packs. Pack authoring and
installation code describe checksums, path safety, licensing and staged
package metadata. The public catalogue includes a Western US pack.

**Useful next features:** previewed layout choices and small, versioned art
packs that can be validated and added on the backend. Preserve E1002 limits
instead of importing its denser layouts wholesale. Keep pack downloads out of
the frame's short wake window.

The Western US ZIP's central directory was inspected through HTTP ranges:
744 members, approximately 428 MiB. It contains no license/attribution/manifest
member. We did not download or verify the full archive checksum. Four sample
images were extracted: raven, dove and goldfinch match the pinned
HABirdDashboard bytes; chickadee differs. Only the verified shared lineage is
recorded. This avoids counting a repackaged image as new artwork.

## Prioritized feature plan

| Priority | Feature | Why / limit |
| --- | --- | --- |
| Next | Persistent diversity cycle per frame | Ensure every eligible species gets a turn; weight recent regional reports within the remaining cycle. Avoid selecting another pose of the same species as if it were a new bird. |
| Next | Art style and variant controls in management | Historical only, illustration only, mixed; favorite or block a specific inaccurate/poor-rendering image. Species controls already work with the expanded catalogue. |
| Next | Winter plumage and western-form gaps | Add reviewed muted goldfinch and red-shafted flicker artwork, improving seasonal credibility rather than simply increasing file count. |
| Later | Web bird detail cards | Reviewed descriptions and reference calls with source credits. Keep the display focused on the bird and readable names. |
| Later | Backend art-pack import/review UI | Preview, hash validation, duplicate detection and approval before activation; preserve rollback and original masters. |
| Optional hardware | Local BirdNET-Go summary adapter | A modern Pi plus microphone or existing RTSP audio; upload only normalized species/confidence/time summaries. No dependency for the gifted frame. |
| Only for catalogue gaps | Grounded generation pipeline | Explicit species/form references, independent review, bounded repairs and quarantine. Avoid unrestricted daily generation and ongoing API spend. |

The strongest alternative is adopting a complete upstream app. It saves some
future feature work, but adds a different UI, detection assumptions and display
workflow to an already functioning sleeping-frame service. Incremental reuse of
art and a few backend ideas is the simpler approach for this gift.

A larger catalogue alone does **not** guarantee an even rotation. Existing
regional weighting and the seven-day repeat penalty remain in force. The
persistent diversity cycle above is a proposed feature, not a claim about this
release. Likewise, microphone classification, call playback and art-pack
management are not implemented by the artwork expansion.

## Provenance and reproducibility

`art/related-art.lock.json` pins the selected file URLs, source revisions and
SHA-256 hashes. `tools/import_related_art.py` can replay the selection after the
base Fugleramme import, refuses changed bytes/curation and preserves masters.
The base importer now refuses to overwrite an existing curated catalogue.

Asset credits stay as ordinary metadata. HABirdDashboard declares code and
artwork MIT from v1.6.0 with contributor agreement; its separate third-party
noncommercial taxonomy files were not imported. Belkins retains its declared
CC BY-NC-SA terms. Inky retains MIT notices and review manifests. The historical
plates are public domain with source/artist credits, and the modern crosswalk
metadata is CC0. Crosswalk revision:
`23e8c4b6dd5ac1d7ba3e304e244c76006963b38a`; image release `havell-v2`, verified
against its published per-file SHA-256 manifest.

The runtime catalogue supports mixed per-asset provenance. An output records
its selected artwork licenses and the applicable composition license, avoids
combining incompatible ShareAlike material, and excludes reference-only plates
from both selection and panel composition. This bookkeeping does not require
owner approvals during normal use.

## Validation

- 25 service tests passed, including reference exclusion, seasonal/plumage
  windows, historical single-art layout, bird capacity and per-asset credits.
- Ruff lint and formatting passed.
- All 73 active masters composed successfully at 800×480.
- Nine representative real Spectra6 conversions passed packed dimensions,
  allowed ink indices and visual review, covering cutouts, flight poses, both
  historical plates and a two-bird composition. Preview colors approximate the
  physical pigments and depend on lighting.
- No firmware flash or unscheduled physical refresh is part of this release.
  New artwork's physical rendering still needs owner observation after a wake.
