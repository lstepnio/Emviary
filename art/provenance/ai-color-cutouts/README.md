# Original AI bird variants

One new original illustration for each of the catalogue's 63 bird species.
These are standalone transparent PNGs, generated from species-specific text
briefs using OpenAI's built-in image generation. No existing artwork, bird
photograph or previously generated image was supplied as an image reference.
The linked Cornell identification pages supplied text facts, not image inputs.

`manifest.json` records each exact generation prompt, original master digest,
species, seasonal eligibility and review decision. `briefs.json` contains the
species-specific briefs. Originals are in `art/masters/emviary-ai-*-v1.png`.
Rejected drafts are excluded from the collection and normal rotation.

The art uses complete, centered silhouettes, natural diagnostic markings,
broad plumage regions and clean alpha. Restrained gray and brown remain where
the species requires them. Six-color e-paper represents those intermediate
tones with dithering; eliminating all dithering would distort many species.
The original PNG alpha is preserved, including invisible RGB under alpha zero.

The review uses Emviary's actual 800x480 Spectra6 packed output, balanced
processing, Lab color matching and Stucki dithering, matching Emily's current
settings. All originals are checked for identification, coherent anatomy and
uncropped extremities; every accepted asset is reviewed in solo and smaller
three-bird compositions. Decoded previews verify the six allowed ink indices.
Physical colors and readability still depend on the panel and room lighting.
Approval means screened and eligible for rotation, not a physical-panel signoff.

Existing artwork and owner exclusions are retained. The new originals use the
same locality weighting, seasonal restrictions, repeat penalties and one-to-three
bird layouts as the rest of the library. Holiday art remains separate.

Reproduce the panel review:

```sh
uv run python tools/preview_ai_birds.py \
  --manifest art/provenance/ai-color-cutouts/manifest.json \
  --output .private/ai-color-cutouts/review
```

The review tool deliberately bypasses seasonal selection so that every asset
can be inspected at once. Runtime selection still applies each asset's months.
