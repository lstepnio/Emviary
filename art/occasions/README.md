# Emviary occasion landscapes

The active collection contains **27 secular, nonbird landscape paintings**,
created with OpenAI built-in image generation and reviewed for the E1002 panel.
Every occasion follows the same vintage landscape-poster and restrained gouache
direction. Scenes vary through terrain, season, composition and time of day.
No ribbons, bows, wreaths, religious imagery or devotional text appear in the art.
The earlier emblem collection remains recoverable in the original PNGs and
[archived manifest](archive/manifest-2026-10-08.json).

[manifest.json](manifest.json) records the exact prompt, original PNG digest,
occasion, date and review status. [v2/prompts.json](v2/prompts.json) contains
the generation briefs. The selected originals live under [v2](v2/). Discarded
still-life drafts are excluded from the active collection. No model identifier
was returned by the built-in tool, so none is inferred.

## Subjects and dates

Colorado meadows, forests, canyons, snow, lakes and moonlit valleys provide most
settings. Dr. Seuss Day uses a playful storybook landscape; Pi Day uses a circular
mountain tarn; Book Lovers Day uses a quiet riverside reading garden. May the
Fourth uses a fictional two-sun desert, with no buildings or characters.
An anniversary landscape is available without creating an undated calendar event.
The existing birthday event uses the new landscape and retains its greeting.

These four requested additions are enabled and repeat annually:

| Occasion | Date | Date reference |
| --- | --- | --- |
| National Book Lovers Day | August 9 | [LA County Library](https://lacountylibrary.org/book-lovers-day/) |
| Dr. Seuss Day | March 2 | [Seussville](https://www.seussville.com/educators/dr-seuss-birthday/) |
| Pi Day | March 14 | [Exploratorium](https://annex.exploratorium.edu/learning_studio/news/march.html) |
| May the Fourth (Star Wars Day) | May 4 | [StarWars.com](https://www.starwars.com/news/the-history-of-may-the-4th) |

## Display review and publication

All 27 originals and all 27 converted 800 × 480 panel proofs were inspected.
Review used the actual production converter and the frame's current processing
and dithering settings, with the current cached forecast. The birthday proof
includes Emily's greeting. This establishes converted output; it does not
replace inspecting the physical panel in its ambient light.

Greetings, titles and weather remain crisp server-rendered text rather than
baked-in image content. The renderer preserves the existing panel safety margin
and fits the artwork without distortion. The ordinary bird catalog, current
last-delivered image, firmware, wake schedule and Wi-Fi configuration are unchanged.
These assets never join ordinary bird rotation or generate bird species counts.
No ongoing AI calls or subscription are required.

The refresh installer preserves the existing artwork IDs, so all existing event
assignments survive. New files use distinct digest-qualified names, and the old
files remain available for recovery. Only the four explicitly requested new dates
are added and enabled; existing dates, repeat flags, enabled flags and greetings
are preserved. Back up service state and artwork before publication.

To reproduce a review and publication from a configured service environment:

```sh
python tools/install_occasion_art.py stage art/occasions \
  --frame emily-e1002 --review-dir .state/occasion-landscape-review
# Inspect originals and panel proofs, then mark the manifest reviewed.
emviary backup
python tools/refresh_occasion_art.py art/occasions .state/occasion-landscape-review
```

The standard staging command omits weather for a neutral layout review. The
production review additionally checked the current weather line and birthday
greeting. Repeating publication adds no duplicate images or events. Review
art at [Special-day art](https://emviary.majjix.com/manage/event-art), and dates,
greetings and test previews at [Special days](https://emviary.majjix.com/manage/events).
