# Colorado wildlife collection

Twelve original, text-only AI natural-history illustrations: raccoon, mule deer,
coyote, red fox, elk, black bear, bobcat, beaver, bighorn sheep, pronghorn,
American pika and yellow-bellied marmot. Built-in OpenAI image generation was used;
the exact prompts are in ../provenance/colorado-wildlife/manifest.json.

Each transparent PNG master is registered in ../catalog.json with category
`wildlife`, animal group `mammal`, region `US-CO`, habitat/search tags, seasonal
eligibility, content hash and attribution. Habitats are editorial curation tags,
not live sighting evidence. Bear and marmot eligibility favors their active season.
Colorado membership is grounded in Colorado Parks and Wildlife species profiles.

The backend offers wildlife twice a month when enabled in Appearance: one stable
surprise in each half-month, avoiding enabled special days. It uses only regional
wildlife, rotates unused or least-recently-rendered species, and falls back to birds
if wildlife is excluded, unavailable or outside the region. Bird observation APIs
do not rank mammals. Ordinary days remain bird compositions; special days retain
their own art. No extra ESP32 wake or processing is introduced.

Every master has been inspected in the actual centered 800x480 Spectra 6 packed
output with Stucki dithering. Rendered images retain the current weather, names,
border and seasonal controls. Masters are preserved; scaling, color mapping,
dithering, paper-white and neutral-text preservation happen on the backend.
Physical panel review remains separate from the digital preview inspection.

## November collection expansion

Sixteen new illustrations add ten Colorado species. Moose, plains bison,
mountain goats and mountain lions each have two versions. The collection also
adds black-tailed and Gunnison's prairie dogs, fox squirrels, two color phases
of Abert's squirrel, Colorado chipmunks and golden-mantled ground squirrels.
The existing red fox gains a black-phase illustration under the same species.

Young bison and mountain goats, antlered moose, and some smaller mammals have
seasonal rotation windows. Bison illustrations represent Colorado's managed
conservation herds. Individual reference links, prompts, and render hashes are
in [the expansion manifest](../provenance/colorado-wildlife/expansion-2026-11-09.json).

## Mule deer, elk, bighorn sheep and black bear variants

Each of these animals has three illustrations. The mule deer adds a buck and
spotted fawn, the elk adds a bugling bull and resting calf, and the bighorn
sheep adds a walking ewe and resting lamb. Black bears gain cinnamon and
blonde color phases. The antlered, rut and juvenile illustrations have their
own seasonal windows. Both new bear colors follow the original bear's April
through November eligibility. See [the variant manifest](../provenance/colorado-wildlife/variants-2026-11-09.json)
for references, prompts and packed-render hashes.

## Pronghorn, coyote, bobcat, pika and marmot variants

The pronghorn gains a running doe and resting fawn. The coyote gains trotting
and howling poses, and the bobcat gains stalking and resting poses. The pika
is shown gathering grass and scurrying. The marmot gains sunning and sentinel
poses, both within its existing May through September rotation window. The
pronghorn fawn and haying pika have summer rotation windows. Each animal's
three portraits share one species identity. See [the second variant manifest](../provenance/colorado-wildlife/variants-five-2026-11-09.json)
for references and render checks.

## Riparian and small mammal variants

The last seven subjects with a single portrait each now have three. Raccoons
gain walking and reaching poses, while beavers are shown walking and gnawing
a willow twig. Black-tailed prairie dogs gain running and grazing poses;
Gunnison's prairie dogs gain sentinel and resting poses. Fox squirrels gain
leaping and resting poses, Colorado chipmunks gain running and feeding poses,
and golden-mantled ground squirrels gain upright and running poses.

The additions share their original species identities and eligibility months.
See [the third variant manifest](../provenance/colorado-wildlife/variants-seven-2026-11-09.json)
for references, prompts and packed-render hashes.

## Wally

Wally, a domestic dog, appears in four photo-guided illustrations: seated,
standing, resting with his plaid bandana, and walking. They use the same solo
animal slots and repeat avoidance as the Colorado collection. All four share a
single species identity and are eligible year-round. The original photos are
private. See [artwork provenance](../provenance/wally.json).
