# Emviary product, accessibility and resilience review

Reviewed October 8, 2026, Mountain time. Application release: 0.9.0.

## Direction and scope

A quiet field-journal interface: forest-green navigation, warm neutral canvas,
readable typography and artwork as the focal point. Keep native HTML controls and
server-rendered pages. Small progressive enhancements improve recovery and feedback
without a client framework, polling or additional device wakeups.

The core journeys are inspecting current and next art, changing appearance,
configuring and previewing special days, curating images, staging gift Wi-Fi,
checking device health and recovering a frame. Existing capabilities, credentials,
public/private boundaries and the three-bird cap remain intact.

## Prioritized findings and implementation

| Priority | Observed issue | Impact | Change | Effort |
| --- | --- | --- | --- | --- |
| High | Failed forms navigate to a generic error page | Entries and context are lost | Preserve the editable form on errors, focus an accessible error message, permit correction | Medium |
| High | Historical preview always described as queued | Owner could misunderstand the next image | Distinguish currently queued, last delivered and historical artwork using stored state | Small |
| High | Removed cached image can satisfy preparation; old cursor can return removed art | Removed content may reappear | New revision for hidden cached art; safe navigation fallback, with regression tests | Small |
| High | Full master images used for gallery cards | Large transfers for small previews | 480×360 maximum web thumbnails, bounded 64-entry cache and ETags | Medium |
| Medium | Long-running actions offer no working feedback | Repeated submits and uncertainty | Disable initiating button, announce pending operation, preserve native form fallback | Small |
| Medium | Owner deep links lose destination at sign-in | Unnecessary navigation | Allowlisted return destination; API/image authentication remains intact | Small |
| Medium | Nine equal navigation items and repeated overview cards | Weak hierarchy and excess space | Group frame, collection and setup; compact overview status; larger artwork emphasis | Medium |
| Medium | Color-processing choices mixed with ordinary settings | Expert complexity too early | Advanced processing disclosure; dependent weather options; bulk bird selection | Small |
| Medium | Gallery actions discard filters and paging | Curating a collection becomes repetitive | Preserve validated context and show recoverable removal/restoration confirmations | Small |
| Medium | Input boundaries are only 1.79:1 against white | Controls harder to identify | 3.63:1 form boundary; preserve visible focus and keyboard skip navigation | Small |
| Medium | Battery ignores selected frame and uses raw UTC | Misleading context and poor readability | Honor selected frame, share Mountain timestamps, disclose estimate requirements | Small |
| Medium | Special-day order reflects insertion order; new event claims Enabled | Difficult calendar review | New editor first, enabled upcoming events before disabled/past, show effective occurrence date | Small |
| Low | Public and error pages use inconsistent presentation | Fragmented experience | Shared responsive shell, restrained public heading, branded HTML error states | Small |

## Acceptance criteria and evidence

- Common settings remain available; advanced controls are progressively disclosed.
- At 320 and 390 CSS pixels, pages have no page-level horizontal overflow.
  Tables may scroll within their own container.
- Form controls have labels and images have alternative text; error feedback can
  receive keyboard focus. Skip navigation reaches the main landmark.
- Failed settings remain editable with the attempted values in a JavaScript-enabled
  browser. No credentials are placed in URLs, persisted browser storage or error text.
- The initiating submit button cannot submit the same form twice while pending.
- Preview preparation does not claim a physical-panel update. Reopening a historical
  preview does not claim it is still queued.
- Collection actions retain frame/filter/pagination and provide truthful confirmation.
- Browser sign-in return destinations are restricted to owner pages on this app.
- Public pages do not expose owner settings or diagnostics; frame APIs retain their
  original authentication and image response behavior.
- Thumbnail generation cannot alter original masters or frame rendering.
- A removed image cannot satisfy cached preparation or a stale navigation boundary.

Validation performed:

- Full Python regression suite, targeted UX/resilience tests and Ruff checks.
- Browser walkthrough of the overview, appearance, special days, image history,
  artwork, occasion art, health, settings, recovery, public frame and public library.
- 320-pixel reflow checks on all ten core pages; 390-pixel form-error review.
- Real invalid bird-selection submission: focused error and form entries retained.
- Keyboard Tab/Enter skip-link navigation to the main landmark.
- Computed color ratios: body 12.92:1; muted text 5.16:1; input boundaries 3.63:1;
  sidebar links 9.30:1; focus outline on white 5.06:1.
- A representative 24 approved-image set decreased from 9,210,788 bytes of masters
  to 495,934 bytes of thumbnails, a 94.6% reduction. This is a local payload
  measurement, not a real-user performance study.
- Shared CSS/JS are content-versioned and cached; HTML and owner responses remain
  no-store. Cache memory is bounded and original artwork endpoints remain available.

## Limits and follow-up

This review is not a WCAG certification. Real VoiceOver/NVDA testing and native
browser 200% text zoom remain manual acceptance checks. Narrow-screen reflow is
verified, but it does not substitute for those checks. All validation measurements
are laboratory observations rather than field performance data.

The public mirror follows the last delivered image. Neither this UI nor a successful
API response independently confirms what is visible on the physical panel. Device
refresh overlap observed in earlier hardware testing remains a separate firmware
issue. No firmware is changed in this release.

Future improvements should follow observed use: an artwork picker with visual
search, field-linked server validation summaries, conflict warnings for simultaneous
special days and real-user performance instrumentation. They are not required to
use or recover the current core flows.

Screenshot evidence is kept privately under `.private/ux-review/` rather than
publishing owner telemetry or configuration in the public repository.
