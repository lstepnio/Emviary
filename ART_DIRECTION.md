# Artwork and evidence rules

The backend owns selection, composition, layout, scaling, palette processing,
dithering, forecasts and schedules. The E1002 downloads a ready image and sleeps.

## Evidence

One site center and radius apply to both bird sources. BirdWeather stations are
filtered by great-circle distance before querying their detections. The station
lookup is bounded to 100 candidates and species responses to 32. eBird reports
use the same radius and are checked against it again; responses are capped at
100 species by default. Neither adapter expands to a distant region silently.

Scientific names map observations to the reviewed artwork catalog. Unsupported
species are never illustrated speculatively. Acoustic counts receive a capped,
sublinear weight; eBird supplies a presence bonus rather than an added count.
Sensor coverage and observer effort bias both sources. These are regional
reports, not evidence that a bird visited the recipient's garden.

Source windows, radius, center, retrieval times and fallback state are recorded.
Changing locality invalidates cached evidence from the old scope. Older bird
evidence expires after 48 hours; a forecast must match the artwork's local day.
No current evidence means a seasonally eligible curated bird, not a fabricated
observation. Observer locations and checklist identifiers are discarded.

## Display

Use the existing curated bird cutouts without regenerating diagnostic plumage.
Never stretch, recolor, mirror or invent a bird pose. Resize with aspect ratio
preserved. The 800×480 E1002 supports one to three birds, default maximum three.
Multiple birds use separate cells with aspect ratios preserved. Three-bird
labels can wrap over two lines; scientific names remain in a separate line.
Selection and layout are saved before conversion, making retries reproducible.

Quiet paper, strong text and restrained edge treatments keep dithering readable.
The management preview simulates the actual packed palette choices; physical
pigments and lighting still differ from a screen. The public image follows the
last frame delivery rather than a newly prepared composition.

Seasonal motifs follow the local calendar. Forecast cues stay behind the bird
layer and in the margin: a small sun or sky-line sketch with a short condition label, rainfall
likelihood, forecast snowfall or strong wind. Pale filled cloud blobs are excluded.
Weather marks use strong strokes in the header, away from bird silhouettes. Do not imply measured garden conditions. Do not add snow from a
low temperature alone. Missing or stale forecasts produce no weather cues.
The printed date identifies the outlook if the frame retains an older image.

## Optional AI work

No online generation is enabled in the POC. Existing art is sufficient.
If generation is added, begin with background treatments or missing variants,
not unrestricted daily pictures. A request must contain a reviewed species
reference, geographic/season eligibility, a named style, an approved palette,
layout bounds and explicit limits on visual weather cues. Weather should be
translated from validated data into a small set of approved treatments.

Generated work enters a quarantine library. Check anatomy, diagnostic markings,
pose, duplicate limbs, ungrounded species, unintended text, licensing and the
physical panel before approval. Never send an unreviewed generation directly
to the frame. Store its model, prompt, references and review decision. Keep a
reviewed fallback available if a generation or review fails.

Pure white source pixels stay white in the packed panel output. Paper texture
comes from the physical display; artificial paper grain is omitted to avoid
colored dithering in empty areas. The palette conversion still handles all
colored artwork and motifs.

Picture-quality renderer version 3 uses LAB matching against the pinned perceived
Spectra6 palette, retaining the owner's diffusion and tone-preset controls.
Neutral text, weather marks and thin rules are packed as black/white in bands
outside the bird cells. Borders and the label separator use neutral ink rather
than pale tan that breaks into colored dots. Colored plumage remains subject to
six-color conversion; neutral-graphics correction never touches bird cells.

## Expanded library (renderer version 4)

The catalogue includes historical cutouts, selected existing generated cutouts,
and historical full-art crops. Source masters remain unchanged. Historical
plates appear alone and retain every depicted bird; the capacity check counts
birds in the source, not just catalogue entries. Text-heavy field-study plates
are web references and cannot be selected or composed for this panel.

Approval means accepted for backend rotation after visual screening; it does
not certify ornithological accuracy or physical display quality. Those limits
are recorded per asset. Bright breeding plumage can have narrower eligibility
than the species itself. Regional provider weighting never overrides the
seasonal and owner species filters. See research/RELATED_PROJECTS.md.

## Special dates (renderer version 5)

Configured special dates use a single bird, a drawn birthday/anniversary/
celebration/remembrance motif, an occasion heading and an optional greeting.
The bird remains unchanged. The layout reserves separate bands for the artwork,
species labels and greeting; neutral text is packed as black/white without
changing bird pixels. Preview uses the actual Spectra6 conversion and does not
publish an image or change the current frame delivery.

Annual dates use Denver month/day, one-time dates match the full date. The first
enabled match wins; February 29 is not moved in non-leap years. An explicitly
chosen approved seasonal artwork takes precedence over the ordinary species
filter for that occasion. If it later becomes unavailable, seasonal selection
is the fallback. Normal rotation resumes on the next day.
