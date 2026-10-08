# E1002 picture-quality audit, 2026-10-08

The E1002 is 800×480, 7.3-inch Spectra6. The approved RGBA masters range from
367×475 to 1200×808 and are resized once with Pillow Lanczos, preserving aspect
ratio. Bird cells are limited to 302×285 for two birds or 572×313 for one.
Small two-bird layouts trade feather detail for diversity.

The production output uses the pinned epaper-image-convert 0.1.21 converter,
balanced tone processing and Stucki diffusion. Its perceived Spectra6 palette
matches PhotoFrame's default RGB values exactly. Those values are generic defaults,
not a measurement of this particular panel under the recipient's lighting.
The preview decodes actual packed indices using those approximate perceived colors.
A browser's scaled JPEG can introduce its own moire and cannot certify physical PQ.

PhotoFrame v2.19.0 and our pinned fork accept EPDGZ as display-ready. GUI_ReadEPDGZ
decompresses it and passes the indices to Paint_SetPixel without re-dithering.
The E1002 ED2208_GCA driver sends the packed buffer. Our firmware diff does not
modify palette processing or the image transfer path. No firmware flash is needed.

Seeed's current public SD_ImagePipeline_E1002 reference defaults to Floyd-Steinberg
with gamma 1.0, offers Bayer/Jarvis/Atkinson, and uses a different color-index
contract in its Seeed_GFX path. Its reference RGB values are not panel calibration.
Do not copy those raw indices into PhotoFrame EPDGZ. Factory SenseCraft HMI is a
separate cloud processing path; its complete production image-processing algorithm
was not verified from available source. Public examples are not proof of factory
behavior or quality.

Six same-source conversions compared RGB/LAB, Stucki/Floyd/Sierra, and disabled
range compression. Disabling compression washed out fine text and highlights in
the preview. LAB matching was selected to reduce chromatic artifacts in neutral
tones; Stucki remains the owner-selected diffusion algorithm. The simulation is
not a substitute for a physical comparison.

Renderer version 3 adds LAB matching and preserves neutral header/footer/edge
pixels as black/white ink after conversion. These regions exclude bird cells and
botanical artwork. Thin rules now originate in neutral ink. Pure white remains
white. A packed-pixel regression verifies the separation from colored art.
All 21 tests and Ruff pass. Native-resolution comparison artifacts remain private.
Physical review is pending before calling panel quality verified.

Sources:
- https://wiki.seeedstudio.com/getting_started_with_reterminal_e1002/
- https://github.com/Seeed-Projects/OSHW-reTerminal-Series-E-D/tree/main/examples/base/SD_ImagePipeline_E1002
- https://github.com/aitjcize/epaper-image-convert
- https://github.com/aitjcize/esp32-photoframe/tree/v2.19.0
