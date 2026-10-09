# Emviary occasion artwork

21 nonbird illustrations cover the 28 holiday and meteorological-season entries
configured on October 8, 2026. Matching next-year holiday entries reuse the same
illustration. These are AI-generated illustrations, not photographs or historical
documents. OpenAI built-in image generation created each original; Emviary curated
the subjects and reviewed both the originals and converted panel proofs.

[manifest.json](manifest.json) records the source PNG SHA-256, exact generation
prompt, occasion, representative preview date and review status.
[prompts.json](prompts.json) retains the subject briefs alongside the prompts.
Original PNGs are preserved without retouching. No model identifier was returned
by the built-in generation tool, so none is inferred or recorded.

## Display treatment

- Centered, broad silhouettes and restrained poster/gouache styling, with a
  white or cream background and space around the main subject.
- No birds, baked-in words, dates or watermarks. Titles and optional greetings
  remain crisp service-rendered text.
- The renderer fits nonbird art into a 752 × 364 region when the greeting is
  empty, or 752 × 326 when a greeting is present, on the 800 × 480 E1002 canvas.
  It preserves aspect ratio and the panel safety margin.
- The current frame's processing and dithering settings drive the pinned
  Spectra6 converter. Validation checks the exact six-color packed panel data.
  Fine printed texture remains visible; this is a stylistic choice rather than
  photographic detail. Preview palette colors approximate the physical panel,
  which still requires inspection in its ambient lighting.

The full originals are wide 1619 × 971 PNGs. Representative dates only select
review conditions; installation never changes the configured calendar dates.
The four seasonal illustrations use Colorado mountain, meadow, aspen and snow
subjects. Juneteenth, MLK Day, Veterans Day and Memorial Day use symbolic art,
not literal historical depictions or official flags.

## Install and manage

Stage with production-equivalent configuration and the actual converter:

```sh
uv run python tools/install_occasion_art.py stage art/occasions \
  --frame emily-e1002 --review-dir .state/occasion-review
```

Inspect every original and panel proof, then set `reviewed: true` in the manifest.
Back up application state before installing:

```sh
uv run emviary backup
uv run python tools/install_occasion_art.py install art/occasions
```

The installer verifies original hashes, adds provenance to the separate event-art
library, approves reviewed images, and assigns art to matching occasion labels
only where no image is already selected. It is safe to repeat. Existing event
enablement, dates, recurrence, messages and custom art selections are preserved.
At initial installation all 28 entries were disabled; enable desired events in
management. These images never enter the ordinary bird rotation and generate no
bird render counts. No ongoing AI generation or subscription is needed.

Review art at [Special-day art](https://emviary.majjix.com/manage/event-art), and
control dates, greetings, enablement and private frame previews at
[Special days](https://emviary.majjix.com/manage/events).

The management preview button uses today’s real forecast and queues the exact
converted image for testing through the next refresh or right-button press.
The calendar date and enabled flag stay unchanged. Direct preview image URLs
remain read-only. Daily scheduled generation continues normally after testing.
