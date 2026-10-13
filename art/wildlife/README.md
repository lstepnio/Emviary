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
