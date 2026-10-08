# Bird artwork research and source audit

Reviewed 2026-10-08 for Emviary's Colorado frame: 800×480, six-color Spectra6,
nightly prepared images, and a maximum of three depicted birds. This pass adds
**seven reviewed assets**: five AI-generated pencil studies and two complete
Fuertes paintings. Rotation grows to **143 images / 62 Colorado species**.
Masters are unchanged; source credits are visible in `/library`.

## Western US archive: measured results

The supplied [BirdFrame archive](https://avianassets.simenf.com/avianvisitors-western-us.zip)
was downloaded completely and its SHA-256 verified against the
[BirdFrame catalog](https://github.com/simenf/birdframe):

- 448,470,320 bytes; SHA-256 `8eede62f86b859b6a3b7e508c96afbaa17d99c194823ba643a782468d4dc1252`.
- 744 entries: 666 illustration PNGs, 76 sketch PNGs, `dims.json`, `masks.json`.
- The 666 illustration filenames form 333 paired species slugs. This is a
  Western-US-labelled source pack, not 333 individually verified Colorado taxa.
- **92 PNGs exactly match existing Emviary master hashes.** This measures byte
  equality, not independent artists or biological correctness.
- No license, attribution, or package manifest file is present in this ZIP.
  Credits and declared terms come from the original project, not the ZIP's name.

The [BirdFrame source](https://github.com/simenf/birdframe/tree/de9c32e4ab4743f6313549821a15f6caa3fd8127)
remains at the previously reviewed revision. The five imported sketch members
also match the original [AvianVisitors source](https://github.com/Twarner491/AvianVisitors/tree/2f18a66676b85d9548cfcbca21d94a4aab88e17a/avian/assets/sketches)
byte for byte. Do not bulk import the pack or silently infer that every filename
is a current Colorado taxon. For example it lacks a `pica-hudsonia.png` member;
common-name guesses would hide taxonomy/coverage errors.

## Ranked sources and actual display fit

| Source | Concrete artwork or coverage | Fit and action |
| --- | --- | --- |
| [AvianVisitors pencil studies](https://github.com/Twarner491/AvianVisitors/tree/2f18a66676b85d9548cfcbca21d94a4aab88e17a/avian/assets/sketches), also in BirdFrame ZIP | Raven, Mourning Dove, Western Bluebird, Dark-eyed Junco and White-crowned Sparrow imported; 76 sketch files available | Transparent line art adds a distinct treatment. Fine detail caps imported variants at two birds. Monochrome art deliberately omits color-specific field marks. Source README and official bundle catalog declare CC BY-NC-SA 4.0. |
| [AvianVisitors official bundle catalog](https://github.com/Twarner491/AvianVisitors/blob/2f18a66676b85d9548cfcbca21d94a4aab88e17a/avian/frontend/assets/bundle-catalog/catalog/bundles-v1.json) | Japanese Woodblock and Evolutionary Impressionist, each declared 333 species, Western North America including US-CO | Woodblock overlaps existing color art. Five Impressionist sample PNGs were inspected, not imported: their scribbled outlines lose diagnostic plumage. The full manifest API returned 403; no successful full Impressionist-bundle inspection is claimed. Catalog terms are CC BY-NC-SA 4.0. |
| [USFWS Western Tanager](https://www.fws.gov/media/western-tanager-7) and [Clark's Nutcracker](https://www.fws.gov/media/clarks-nutcracker-0) | Louis Agassiz Fuertes paintings, species-tagged records, explicit Public Domain | Both imported as unchanged complete scenes. Tanager has two birds and May–September eligibility; Nutcracker has one. Whole scenes appear alone, preserving branches/background. Portrait Tanager uses less panel width; Nutcracker is a stronger landscape fit. |
| [Birds of the Rockies, Keyser/Fuertes, 1902](https://www.gutenberg.org/ebooks/25973) | Williamson's Sapsucker, Green-tailed/Spotted Towhee, Lazuli Bunting, Lark Bunting, Western Tanager, Townsend's Solitaire, Ruddy Duck, Brown-capped Rosy-Finch | Excellent local provenance and coherent landscape studies. Sampled Gutenberg plate images are only 249–500 pixels wide, so prefer larger BHL/Commons scans before ingesting. Count background birds too: Ruddy Duck plate has a distant flock and exceeds our three-bird cap. Historic names need current taxonomy mapping. Public domain in the USA. |
| [Western Bird Guide, Reed/Harvey/Brasher, 1917](https://www.gutenberg.org/ebooks/45918) | Western grebes, ducks, owls, grouse, passerines; small illustrated species entries | A different field-guide style and useful coverage leads. Individual images need size/bird-count review, especially mixed-species pages. Historical taxon names require crosswalks. Public domain in the USA. |
| [Cassin's western illustrations](https://www.gutenberg.org/ebooks/66068) | Western North American plates, including regional forms | High-priority route for gaps such as western woodpeckers and upland birds. Find a sufficiently large page scan and verify modern identity; don't use a historical common name as a direct API species key. Public domain in the USA. |
| [USFWS Fuertes Swallows](https://www.fws.gov/media/swallows-illustration) and [Grosbeaks](https://www.fws.gov/media/evening-rose-breasted-grosbeaks) | Explicit Public Domain records, downloadable originals | Useful artist-consistent expansion beyond the two imported records. Some scenes contain multiple taxa; need separate crops or a future multi-species caption contract before automatic rotation. |
| [Cornell Fuertes collection](https://rmc.library.cornell.edu/Birds/) | Approximately 2,500 bird illustrations, multiple collections | Strong species/pose discovery and identity references. Item permissions differ; record the actual item's terms. A collection landing page is not itself a downloadable art pack. |
| [Library of Congress Birds](https://www.loc.gov/free-to-use/birds/) | Audubon, Alexander Pope, Louis Prang, drawings and photographs | Source variety beyond isolated scientific cutouts. Review species and count before importing. Generic decorative birds belong to special-day art, not an invented species identification. |
| [Smithsonian Open Access](https://www.si.edu/openaccess) / [BHL](https://about.biodiversitylibrary.org/help/copyright-and-reuse/) | Historic illustrated books and CC0-designated image records | Scans with known author/page provenance can fill regional gaps. Check item-level download, resolution and rights. A book catalog record or cover thumbnail is not evidence of usable full plates. |
| [Cleveland Open Access](https://www.clevelandart.org/open-access), [NGA free images](https://www.nga.gov/artworks/free-images-and-open-access) | CC0/open-access fine-art records | Good for special-day art and backgrounds. Most bird-themed fine art is not a reliable Colorado species illustration. No art from these collections was imported in this pass. |
| [Inky Bird Frame](https://github.com/veteranbv/inky-bird-frame) | AI field-journal pages with source references and review artifacts | Valuable review workflow; dense page text becomes small on this panel. Existing three journal pages remain web references. Do not treat a generated page's review as proof every included factual detail is correct. |

These are distinct source opportunities, not claims that all images in each
collection were visually reviewed or added. Community AvianVisitors forks mainly
extend geography in the same style; more forks do not automatically increase
visual diversity. Paid stock sites offer many generic AI birds, but an isolated
stock search result provides weaker taxonomy, provenance and repeatable downloads
than the sources above. No stock subscription is needed for this project.

## What was screened out

- Evolutionary Impressionist: genuinely different style, but currently too abstract
  for the project's species-grounded illustration rule. Keep as an optional
  experimental-art direction, not automatic bird-selection output.
- Generated Mountain Chickadee: the reviewed pack sample lacks the white eyebrow.
- Generated Woodhouse's Scrub-Jay sample: head/body color and field-mark rendering
  are not convincing enough for approval.
- Generated Northern Flicker sample: regional-form/plumage review needed; a
  western-scoped archive does not establish red-shafted identity.
- The low-resolution Ruddy Duck page: more than three depicted birds, including
  the distant flock. Importing only foreground count would violate our cap.
- Low-resolution multi-species or densely annotated scans: a master worth
  researching can still be a poor 800×480 display asset.

## Grounded AI enhancement plan

Prefer improving coverage gaps and alternate poses over generating another large
batch of the same species in the same stance. First shortlist Brown-capped
Rosy-Finch, Green-tailed Towhee, Lewis's Woodpecker, Red-naped Sapsucker,
Burrowing Owl and Red Crossbill. Each is a candidate, not an already approved
or guaranteed common local bird.

For each new generation or restyle:

1. Supply a current species reference, a reviewed historic source and western
   form/sex/season notes. Keep author and source URLs with the candidate.
2. Name a style explicitly: restrained gouache, bold woodcut, or clean ink study.
   Request one complete bird, isolated transparency, broad tonal/color regions,
   visible eye/beak, sensible feet and a usable pose. Avoid invented wing bars,
   extra limbs, dense scenery and tiny embedded lettering.
3. Generate one candidate at a time. Preserve the source master; store prompt,
   tool/model when known, references, parent artwork and review decision.
4. Inspect anatomy and markings before conversion. Then preview at realistic
   single, pair and trio sizes through the pinned Spectra6 LAB/dither pipeline.
   A source with fine lines may be capped at one or two birds even when policy
   permits three. Enforce that cap in backend selection.
5. Review on the physical panel before approving new Emviary-generated work.
   The existing Mountain Bluebird woodcut remains a pending prototype. Don't
   turn an automatically generated batch straight into nightly rotation.

Generation stays a one-time curation task. The frame continues to download
prepared art and sleep; no nightly paid generation or new device workload is
introduced. Existing source sketches are marked AI-assisted in the library.
The source masters retain gray shading; the current color converter may produce
small colored dither speckles in gray regions. A dedicated neutral-only art
rendering mode would be a separate improvement, especially if physical review
shows unwanted tint. It was not silently implemented or claimed in this pass.

## Reproduction and audit trail

`art/diversity-art.lock.json` pins the seven selected direct source URLs, individual
SHA-256 digests, archive checksum/contents audit, attribution notices, pose/facing,
bird counts and composition limits. Replay with:

```sh
python tools/import_related_art.py --lock art/diversity-art.lock.json
```

The full 448 MB archive and rejected samples stay in the ignored `.private/`
research directory. Only the seven selected masters, small metadata locks and
research notes enter Git. Their art fits existing service logic without a new
firmware or backend code release. Public library entries retain source links
and notices. Research previews establish digital fit; pigment appearance and
long-term stability still require the physical frame.

## Follow-up sources suggested by the owner

The individual review of Audubon, Library of Congress, Unsplash, Magnific and Vecteezy is recorded in [USER_ART_SOURCES_2026-10.md](USER_ART_SOURCES_2026-10.md). Two complete two-bird scenes entered rotation and one three-bird portrait plate remains reference only.
