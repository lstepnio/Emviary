# Emviary 0.12.0 experience and service review

Reviewed October 12, 2026. Baseline: application 0.11.1, container
`emviary:poc-040`. Candidate: application 0.12.0, `emviary:poc-041`.
The live frame's saved 04:15 Denver schedule, preferences, art, events,
credentials, firmware v0.8.1 and 512 MiB memory limit are preserved.

## Findings and completed changes

| Journey | Baseline finding | Implemented result |
| --- | --- | --- |
| Understand what happens next | Three equally prominent images obscure the current artwork; delivery can be confused with panel confirmation | Larger last-delivered image; separate daily and next-button cards; readiness uses the actual cache eligibility check; device-reported refresh evidence remains in health |
| Appearance | Settings cannot be reviewed before saving; saving alone can leave prepared art with earlier settings | Render unsaved settings, then save only or save and queue the exact reviewed bytes; state explicitly distinguishes draft, saved, queued and delivered |
| Expired sign-in | An open form keeps its old CSRF token after signing in elsewhere | Authenticated no-store session preflight refreshes CSRF; sign in in another tab and retry while retaining entries; no automatic replay or browser storage |
| Slow or failed actions | Multiple forms or controls can change during a pending request | Capture payload and lock all form-associated controls; focused error summaries retain values and link to affected fields; unlock after failure |
| Conflicting edits | Separate tabs can silently overwrite newer frame settings | Revision checks reject stale appearance, Wi-Fi and calendar edits; connection/public-display settings use a configuration hash; conflict retains attempted values |
| Special days | Queueing can appear to include unsaved edits; saves lose the current editor | Explicitly queue the saved day; show enabled/disabled counts and existing overlap rules; return to the expanded, focused saved event, including enhanced fetch redirects |
| Occasion art | Assigned art can be removed or unapproved; gallery loads full originals | Explain dependencies and link to using events; prevent removal/unapproval until detached; private cached thumbnails with full-size review links |
| Artwork curation | Bulk scope and counts are weak; a global destructive control sits among filtered actions | Visible-page select/clear, live counts and disabled empty actions; preserve paging, filters and selected-frame context; global cleanup is a separate disclosure |
| Image history | Removing the last item on a page can leave an empty dead end | Clamp to the nearest available page; preserve removed/history context and restore actions; protect last-delivered artwork |
| Navigation and recovery | Sidebar links lose the selected frame; some runbook instructions describe obsolete buttons and previews | Shared selected-frame context through navigation; clear shared-library scope; updated recovery, button, event and preview documentation |

Real-browser testing also found a shared JavaScript defect: controls named
`action` shadowed `HTMLFormElement.action`. The submission handler now reads
the destination attribute explicitly. This was corrected before deployment.

## Shared structure and user flows

Navigation retains the existing three groups: **Your frame** (overview,
appearance, special days), **Collection** (images, artwork, special-day art),
and **Setup & health** (health, settings, recovery). The selected frame is
visible; artwork rotation remains a shared collection across frames.

Native labels, selects, fieldsets, disclosures and links stay in use. Primary
buttons complete the current task; secondary buttons review or navigate;
recoverable removal controls ask for confirmation. Pending operations freeze
form controls and announce progress. Failed operations focus the error and
keep the draft editable. Saved notices clear when inputs are edited.

Appearance: edit, preview, inspect the panel-converted image, then choose
**Save settings only** or **Save and queue preview**. Changing a draft
invalidates its preview. Native HTML preview submission also provides a
working review and queue form. Changing settings alone does not promise that
already prepared artwork has changed.

Special days: create/edit and save first; **Queue saved day on frame** prepares
that saved event using today's available weather without changing its calendar
or enablement. Approval of uploaded art and assignment to an event remain
separate actions. The existing recurring weekday rules and priority determine
calendar conflicts consistently with the compositor.

## Backend contracts and tradeoffs

- The public mirror follows last delivery, not a browser preview or prepared
  slot. Fetch success is not independent physical-panel confirmation. Health
  reports firmware evidence separately.
- Appearance drafts call the production compositor and pinned converter.
  They do not save policy, consume rotation counts or publish images. Saving
  and queueing validates frame, policy, configuration hash, revision, expiration
  and token, then publishes those exact bytes with the policy in one SQLite
  transaction. Queued output persists across restarts.
- Draft storage is bounded to five previews for up to 30 minutes and disappears
  on restart; generating more drafts can evict earlier ones. Re-preview is the
  explicit recovery path. This is simpler than a new persistent draft subsystem
  and limits memory while supporting normal review.
- Rendered owner forms supply revision checks. Legacy API callers may omit them
  for compatibility. A conflict requires comparing current saved settings and
  reloading; automatic merging was rejected because schedules, Wi-Fi and event
  calendars should not be combined silently.
- The existing single application worker, preparation lock, thumbnail decode
  semaphore and disk cache remain. Occasion thumbnails use the same bounded
  decoder and encoding recipe as bird thumbnails, with authentication before
  conditional responses and private revalidation. Original files and frame
  output are unchanged.
- No client framework, dependencies, polling, extra device wakes or firmware
  migration were added. Preview preparation runs off the asynchronous request
  loop. No rendering or provider lookup was added to the frame fetch path.

## Verification and evidence

State-changing browser checks used a clearly marked disposable local copy of
the verified backup, isolated sessions, offline providers and the real image
converter. They could not reach the physical frame or live configuration.

- Full backend regression suite: **198 passed**. Ruff and JavaScript syntax
  checks pass. Existing scheduling, freshness, recurrence, authentication,
  removal/restore, backup and firmware-policy tests remain in that suite.
- Browser success checks: draft preview, save-and-queue, save-only persistence,
  event creation/edit and focused return, saved-event queue/review, artwork
  bulk exclusion on page 2, recoverable deletion/restoration, uploaded art
  review/approval and selected-frame navigation.
- Browser failure checks: expired session followed by separate-tab sign-in and
  original-form retry; stale two-tab save rejection; delayed save with zero
  enabled form controls; injected 503 with retained entries; field-linked
  special-day validation with retained greeting; stale forecast and empty
  new-frame states.
- All 11 core public/management pages have no page-level overflow at verified
  320 and 390 CSS-pixel viewports. DOM inspection found no unlabelled controls.
  A 1280-pixel desktop check confirms the larger last-delivered composition.
- Native Chrome **200% zoom** was observed in the browser's accessibility tree.
  The special-days page remained at 900 CSS pixels with no horizontal overflow.
  Keyboard Enter expanded an event; skip navigation focused the main landmark,
  and Tab reached a visible 44-pixel frame selector at the narrow viewport.
  Save actions become static below 1000 pixels to avoid obscuring focused fields.
- Occasion-gallery payload in the local 28-image fixture: 82,197,208 bytes of
  originals versus 1,266,902 bytes of thumbnails, a **98.5% reduction**. This is
  a laboratory byte count, not a field latency or memory-endurance claim.
- Private screenshots and viewport measurements are under
  `.private/ux-review-20261012/`: baseline overview/appearance, reviewed draft,
  revised overview, special-day save, 200% zoom, and 320/390 reflow JSON.
  Owner screenshots and operational data are excluded from the public repository.

The target is [WCAG 2.2 AA](https://www.w3.org/TR/WCAG22/), including
[focus not obscured](https://www.w3.org/WAI/WCAG22/Understanding/focus-not-obscured-minimum).
This is not a conformance certification. Native browser accessibility semantics
and keyboard behavior were examined; a complete VoiceOver/NVDA journey and
real-user study remain unperformed. A visual artwork picker would improve
search among variants, but the existing native selector remains functional;
it is a separate enhancement rather than a dependency of these completed flows.

## Deployment acceptance

Deploy only the Emviary service after backing up compose, release metadata,
source and a consistent SQLite snapshot. Check installed version and image,
health, public and authenticated pages, memory limits, exact saved policy and
collection counts. Preserve the live 04:15 schedule and existing release/art
metadata. Do not wake the frame for web verification or claim a new physical
panel test. Record the final runtime commit and acceptance below after deployment.
