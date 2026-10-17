# Composition flow review

Reviewed October 16, 2026, America/Denver. Scope: scheduling, rendering, delivery,
public and owner previews, composition history, physical button navigation,
retry handling, and backup/restore. Existing recipient-guide work remains separate.

## Findings and resulting behavior

| Finding | Impact | Resolution |
| --- | --- | --- |
| Composition selection and weather preparation shared a single job | The next day had no useful preview until its weather window | Persist a daily composition and quantized neutral preview in advance; final weather rendering reuses that plan |
| Public Coming up read a raw scheduled slot | Today's delivered image could be advertised as upcoming | Public and owner previews use the same next-wake lookup and reservation |
| History treated each rendered row as a composition | Forecast changes produced visually repeated cards | Group by artwork order, layout, visible appearance, and greeting before applying the history limit; exclude the current composition |
| Button history traversed weather-only revisions | Previous/next could appear to do nothing | Skip revisions of the same composition while preserving immutable historical bytes |
| Selection history was limited to 21 rendered rows | Weather refreshes displaced older unique compositions and biased repetition penalties | Deduplicate composition history before limiting it; apply the same rule to wildlife |
| Wake/freshness changes did not change the scheduled cycle | A completed job for the old schedule could satisfy the new one | Include wake time and forecast age policy in the cycle |
| Root owned the dedicated backup directory after host changes | Scheduler logged PermissionError every minute; navigation queue was starved | Restore UID 1000 ownership and isolate backup errors from the navigation refill pass |
| Library counts described renders as compositions | Weather revisions overstated composition counts | Label the existing counters as renders; planned previews do not increment them |

## Data and interaction boundaries

A reservation is separate from images and prepared_slots. It has no device image
ID, cannot become the active navigation image, and does not update contact,
delivery, or panel state. Preview requests only read saved files and metadata.
Early previews omit weather. At the configured preparation time, the worker adds
fresh weather while retaining artwork, layout, greeting, and appearance. Settings
or library changes invalidate reservations. Preview failures have an independent
three-attempt budget with 15-minute spacing, and cannot prevent final rendering.

Composition identity intentionally ignores forecast snapshots, render revision,
and timestamps. Different artwork order, layout, visible appearance, greeting,
and seasonal decoration remain distinct. Historical images are grouped for
presentation and navigation, not deleted. Earlier composition records do not
prove that each historical render reached the physical panel.

## Verification gates

- Composition persists across restart and remains unchanged when weather is added.
- Rendered pixels below the forecast band match the planned composition.
- Special-day artwork and greeting survive final preparation.
- Owner and public pages return the same planned preview; GET requests never render.
- Public-frame changes and invalid settings invalidate preview access.
- Grouping occurs before card limits, and previous/next skips weather revisions.
- Preview failure, scheduled failure, and backup failure remain independent.
- New backups preserve reserved previews; legacy backups still restore.
- Browser checks cover Coming up, daily refresh, and distinct history on mobile and desktop.

Physical display acceptance of tomorrow's picture still requires the frame's
next normal download and a separate panel observation. Backend and browser checks
do not establish that physical outcome.
