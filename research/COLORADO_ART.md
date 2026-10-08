# Colorado artwork expansion

Reviewed 2026-10-08. This pass adds **64 unchanged masters**, growing the approved
collection from **73 images / 32 species** to **136 images / 61 species**, plus
three reference-only field journals and one quarantined regional-form cutout. There are **29 newly represented species**.
The collection is statewide; a state-list entry is evidence of occurrence,
not proof that a bird is common throughout Colorado or visited a particular yard.

## Sources revisited

The [Colorado Bird Records Committee checklist](https://cobrc.org/Reports/Checklist.aspx)
is the statewide identity/occurrence baseline. Conservative artwork month windows
are curation choices, not precise migration forecasts. [Colorado Field
Ornithologists](https://www.cobirds.org/colorado-birding) explains the diversity of
prairie, mountain and alpine habitats; statewide eligibility should not be
mislabelled as a Denver backyard detection.

The seven GitHub source repositories were refreshed against their current default
branch revisions. HABirdDashboard, Belkins, Inky, Featherframe, BirdFrame and the
historical crosswalk remain at the revisions in `related-art.lock.json`.
[Fugleramme](https://github.com/arnegiacomo/fugleramme) advanced to
`725319a52294c6aefac4c7b9c85429972bac08f0` and supplies particularly useful
historical cutouts. [AvianVisitors](https://theodore.net/projects/AvianVisitors/)
remains the shared illustration lineage behind several apps, not an independent
artist collection to count again.

| Imported group | New images | Contribution |
| --- | ---: | --- |
| HABirdDashboard / AvianVisitors | 40 | Twenty Colorado species, with visually reviewed perched/standing and flight poses |
| Fugleramme historical cutouts | 20 | Audubon, Cassin, Dawson, Fuertes, Gould, Hines, Swainson and von Wright source styles; branches, feeding, flight, and multi-bird scenes |
| Audubon / historical-bird-plates | 4 | Great Blue Heron, Snowy Egret, American Avocet and American Dipper as preserved complete compositions |

New coverage includes Mountain Chickadee, Steller's Jay, Clark's Nutcracker,
American Dipper, Pygmy Nuthatch, Brown Creeper, Canyon Wren, Western Bluebird,
Pine Siskin, Northern Saw-whet Owl, Western Tanager, Lazuli Bunting, Lark Bunting,
Western Meadowlark, Say's Phoebe, Williamson's Sapsucker, Hairy Woodpecker,
Ferruginous Hawk, Swainson's Hawk, Prairie Falcon, Golden Eagle, Osprey,
Sandhill Crane, American White Pelican, American Coot, Black-crowned Night-Heron,
Great Blue Heron, Snowy Egret and American Avocet. American Dipper and Western
Tanager now have both generated and historical alternatives.

## Curation and display limits

Contact sheets were visually reviewed for identity, field marks, pose and bird
count. This is a documented screening, not an independent ornithologist review.
All imported masters remain unchanged. New entries include `style`, reviewed
`pose`, `depicted_birds`, and `composition_max_birds` so rotation can use the
artwork's capacity rather than forcing every image into three narrow slots.
Detailed historical plates remain one artwork per composition. Some historical
cutouts already depict two birds and must count both toward the three-bird limit.
Wide raptor/crane/pelican flight silhouettes are capped at two-art compositions.

Rejected generated Mountain Chickadees: the identifying white eyebrow stripe is
absent. Rejected Gray-crowned Rosy-Finch variants: the illustrated head/bib form
needs closer identity review. The Dawson Mountain Chickadee replacement has the
clear eyebrow and records two depicted birds. [Cornell's identification
reference](https://www.allaboutbirds.org/guide/Mountain_Chickadee/id) and
[Colorado Parks and Wildlife](https://cpw.state.co.us/species/mountain-chickadee)
provide grounding. Historical mixed-species Western Tanager/Lazuli plates with
four or five birds were not added. The Hines Steller's Jay cutout is quarantined because its blue forehead marks
resemble a Pacific form. The Swainson cutout remains eligible. Further regional
forms should be checked against [Cornell's Rocky Mountain identification notes](https://www.allaboutbirds.org/guide/Stellers_Jay/id)
before generating further variants.

Breeding-black Lark Bunting and red-headed Western Tanager art uses May-September
eligibility. Snowy Egret's historical spring-plumage illustration uses April-
September. Other migratory birds have conservative windows recorded per asset.
Resident mountain birds are allowed year-round at the statewide level, without
claiming they live in every habitat. Physical Spectra6 color/readability review of
these additions remains pending. The six-color display still requires actual
800x480 rendered previews and the normal palette/dither pipeline.

## Additional collections worth using

[Audubon's Birds of America digital library](https://www.audubon.org/art/birds-of-america)
provides downloadable high-resolution watercolors. The pinned
[historical-bird-plates](https://github.com/wr/historical-bird-plates) cleaned crops,
SHA manifests and checked modern taxonomy are the most convenient import layer.
Its multi-species and multi-bird sheets need count and identity review before
activation, regardless of filename.

[Smithsonian Libraries' Gould collection record](https://www.si.edu/object/birds-world-over-400-john-goulds-classic-bird-illustrations-maureen-lambourne%3Asiris_sil_612124)
and [Biodiversity Heritage Library North American collections](https://beta.biodiversitylibrary.org/subject/North%2BAmerica)
are useful routes to additional historical artist styles. Cassin's western birds,
Fuertes' North American studies and Dawson's California birds are better starting
points for Colorado gaps than importing Gould's European/Australian catalogue
wholesale. This pass already incorporates reviewed examples through Fugleramme;
new direct BHL cutouts need extraction and review. BHL's Art of Science landing
page returned HTTP403 during this review, so no successful bulk availability is
claimed.

Inky's research/review manifests remain a useful AI-generation design: species
identity references, bounded attempts, independent review and a quarantine state.
Its dense field-journal plates remain web references. BirdFrame and Belkins
mostly redistribute the shared illustration library; importing their entire
packs would inflate file count more than diversity.

## Grounded enhancement workflow

Use AI for missing poses, accurate western forms and genuinely different styles,
not automatically every night. Preserve the original asset and link each
candidate to species references and its parent artwork. Specify plumage, season,
bird count, pose, simple background, complete anatomy, no invented markings and
no embedded text. Prefer editorial watercolor, clean naturalist gouache or
restrained ink wash that survives six-color reduction; avoid photographic
textures, translucent haze and fine patterned paper.

Evaluate anatomy and species identity before approving. Then preview at final
800x480 in each permitted 1-3 bird layout, followed by the actual Spectra6 palette
and dither. Reject variants whose face, feet, wing pattern or silhouette becomes
ambiguous at the chosen size. AI enhancement must remain visibly labelled and
must not silently replace source masters. Style diversity is a rotation feature,
not permission to relax species accuracy.

## Reproducible imports

`art/colorado-art.lock.json` records 64 downloads, hashes and complete provenance.
The existing related-project lock remains replayable with its updated display
metadata. Starting with a base Fugleramme catalogue, run:

```sh
python tools/import_related_art.py
python tools/import_related_art.py --lock art/colorado-art.lock.json
```

The second pass restores the complete combined source collection metadata.
Both passes preserve unchanged masters and reject digest or curated-record
mismatches. Credits remain per asset, with the Colorado historical cutout source
links also in `art/COLORADO-ATTRIBUTION.md`. No paid API, microphone, cloud art
subscription or daily generation dependency is introduced by this import.
