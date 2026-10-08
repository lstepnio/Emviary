# Review of the five suggested artwork sources

Reviewed 2026-10-08 for Emviary's 800×480 six-color E1002, Colorado-wide bird selection, and one-to-three visible birds. Source masters stay unchanged; the backend fits complete plates, adds its own readable labels, and performs the pinned LAB/dither conversion. Digital approval does not claim physical-panel validation.

| Source | Fit for Emviary | Decision in this pass |
| --- | --- | --- |
| [Audubon, Birds of America](https://www.audubon.org/art/birds-of-america) | Identified North American species, botanical scenes, feeding and flying poses. Some historic names need modern species crosswalks. Full plates can contain extra birds or reduce field marks when shrunk. | Add Yellow-billed Cuckoo plate 2 to summer rotation. Add Belted Kingfisher plate 77 as web-only reference. Keep existing Avocet plate 318 instead of duplicating the same composition. |
| [Library of Congress, Birds](https://www.loc.gov/free-to-use/birds/) | Independent artists, chromolithographs, ink drawings and photographs, with stable item records and downloadable images. Species identity needs checking for decorative works. | Add Alexander Pope Jr.'s Mallard pair, 1878. Exclude the four-bird Indigo plate and unverified species in decorative/fable scenes from automatic rotation. |
| [Unsplash, bird art](https://unsplash.com/s/photos/bird-art) | The reviewed search includes museum/public-library uploads alongside Unsplash+ results. Useful discovery route and potential photographic or historic-art references. | No automatic import from a search tag. Prefer the original museum record, a named species, and a usable individual download. Museum duplicates do not add new artistic variety. |
| [Magnific, avian art](https://www.magnific.com/photos/avian-art) | The supplied exact page could not be fetched. The accessible [bird search](https://www.magnific.com/photos/bird) shows premium and AI-generated filters. Potential for isolated, graphic assets and alternate poses, but generic generated birds are not reliable taxonomy. | Research source, no imported assets or subscription in this pass. Require an individual master and species/field-mark review before using a generated item. |
| [Vecteezy, avian artwork](https://www.vecteezy.com/free-vector/avian-artwork) | The supplied exact search page could not be fetched. An individual [Western Meadowlark silhouette](https://www.vecteezy.com/vector-art/38497326-western-meadowlark-outline-silhouette) was accessible and marked Pro. Vectors can scale cleanly, but generic silhouettes lose diagnostic plumage. | Potential for subtle UI/seasonal decoration or a species-verified illustration. No premium-preview or watermark import. No purchase or account change. |

## Imported and reviewed individually

- **Mallard pair**, Alexander Pope Jr., 1878. [LOC item 2018663013](https://www.loc.gov/item/2018663013/), resource `ds.12960`. Two swimming birds in a complete, warm chromolithographic wetland scene. All-month eligibility reflects Colorado Mallard occurrence, not a report at the recipient's home. The 1024×724 provider JPEG is unchanged, including its source edge; its subdued colors produce a deliberately warm, heavily dithered scene. Digitally checked at the final panel size. This work appears alone and requires a two-or-three-bird policy.
- **Yellow-billed Cuckoo**, Audubon / William Home Lizars, plate 2. [Source page](https://www.audubon.org/art/birds-of-america/yellow-billed-cuckoo). Two birds with contrasting feeding poses and botanical forms. June–August eligibility is a conservative curation rule for a rare Colorado summer riparian visitor. [USFWS Colorado survey information](https://www.fws.gov/office/colorado-ecological-services-field-office/yellow-billed-cuckoo-survey-training) supports Colorado occurrence; this does not imply it is common around Denver. Historic scenery and the butterfly interaction are original art, not an assertion of current conditions or a modern behavioral reference. The provider-sized 1600-pixel JPEG was retained without local retouching. Digitally checked through the final six-color conversion; shown alone under a two-or-three-bird policy.
- **Belted Kingfisher**, Audubon / Robert Havell, plate 77. [Source page](https://www.audubon.org/art/birds-of-america/belted-kingfisher). Three birds, including flight and fish-catching poses. The full portrait plate occupies too narrow a region on this landscape display for consistent field-mark readability. Added to the web library as reference only, excluded from frame rotation. A future rearranged derivative would need its own provenance and anatomy/display review.

Both rotation additions retain visible species labels. Physical-panel appearance remains pending. No new generated work was approved, no generation API was added, and nightly operation still uses cached artwork rather than paid generation.

## Screened out and future reference

- LOC's [Indigo Bird](https://www.loc.gov/item/2002718964/) contains **four** birds. Its color target and scan margins also occupy space. It fails the count rule as an unchanged plate.
- LOC's [The swallow and the raven](https://www.loc.gov/item/2010718076/) is an appealing E. Boyd Smith ink drawing, but its generic fable characters do not establish species identity. Its portrait page includes annotations and a stamp. Do not silently label it as a particular Colorado swallow or Raven in automatic selection.
- Audubon's [Mallard plate 221](https://www.audubon.org/art/birds-of-america/mallard-duck) contains four birds, so the Pope pair is a better complete-scene choice for our cap.
- Audubon's [American Avocet plate 318](https://www.audubon.org/art/birds-of-america/american-avocet) is already represented by `audubon-havell-318`. A second digitization is a potential quality replacement, not a fresh pose or style.
- LOC also identifies a [Carol M. Highsmith Burrowing Owl photograph](https://www.loc.gov/item/2018702261/). Metadata identifies a young owl at the Phoenix Zoo, not a Colorado field sighting. This could ground a later illustrated Burrowing Owl candidate. [Colorado Parks and Wildlife](https://cpw.state.co.us/species/burrowing-owl) provides a local species reference. The photograph was not imported or visually approved in this pass.

## Reproduction and credits

`art/user-sources-art.lock.json` records direct image URLs, SHA-256 digests, bird counts, month eligibility, source notices, credits and review status. Replay the reviewed selection with:

```sh
python tools/import_related_art.py --lock art/user-sources-art.lock.json
```

The LOC item's rights advisory reads “No known restrictions on publication”; the original 1878 artwork is in the US public domain. Audubon credits its digital collection to the John James Audubon Center at Mill Grove, Montgomery County Audubon Collection, and Zebra Publishing. These notices remain attached to individual library entries. Search-page tags are not treated as evidence of species identity or download availability.
