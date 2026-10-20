# Management and weather resilience review

Reviewed October 20, 2026, America/Denver. Application release 0.18.0.

## Confirmed findings and fixes

1. The live forecast warning was a false alarm before daily preparation. A valid
   October 20 forecast had been fetched at midnight, but diagnostics required it
   to satisfy the future 04:15 wake before the 03:30 refresh had run. Diagnostics
   now distinguish the current navigation forecast, yesterday's sleeping panel,
   and the daily preparation window. Future-date caches cannot clear an alert.
2. Special days rendered an inline script blocked by the site's existing CSP.
   Quick switches could change visually without saving. The enhancement now ships
   in the permitted external asset. It refreshes session/CSRF before saving,
   handles concurrent edits, and distinguishes an unconfirmed network response.
3. Missing saved credentials produced unusable manual recovery download links.
   The page now exposes those downloads only for an authenticated matching token
   and directs other cases to guided USB restoration. Credentials are never
   synthesized or rotated by a status-page visit.
4. Unknown frame lookups on multiple preview/configuration/library routes raised
   unhandled ValueError. A typed missing-frame error now gives a controlled 404.
5. Missing/unreadable frame previews now give an actionable 503 instead of a
   deferred FileResponse exception. Corrupt/naive/future frame contact timestamps
   no longer prevent management pages from loading.
6. Corrupt optional provider JSON/timestamps could abort all input collection.
   Invalid entries are ignored/refetched, individual source failures stay isolated,
   and bird fallback uses the injected clock consistently.
7. A successful weather-free daily render previously ended daily preparation,
   even if weather returned before wake. The same reserved composition now gets
   bounded retries at least 15 minutes apart, within the existing total budget
   of three attempts and only before its scheduled wake.

## Weather policy

- Two independently delivered APIs: Open-Meteo and the US National Weather Service.
  They can share underlying meteorological models; they are not two statistically
  independent observations. Neither guarantees availability or forecast accuracy.
- Independent per-site, per-date, per-source cache and 15-minute failure backoff.
  Disabling either source still permits the other. Management/image request paths
  never fetch weather. Fetch failures do not block a weather-free composition.
- Open-Meteo uses validated daily Celsius extrema, cm snowfall, km/h wind and
  prevailing daylight WMO sky conditions. NWS uses the point-to-grid discovery
  API, explicit SI units, interval overlap with the local calendar day, daytime
  high and predawn overnight low. DST uses actual local-day boundaries.
- NWS sky is duration-weighted over 08:00-18:00 local, requiring at least eight
  hours of coverage. Snow accumulation crossing midnight is apportioned by
  interval overlap. These are explicit approximations, not observed conditions.
- Reject date mismatches, invalid/nonfinite/out-of-range values, incompatible
  units, incomplete temperature/daylight coverage, and stale/future timestamps.
  Preserve NWS issuance separately from fetch time, rejecting issuance older than
  18 hours. A new download cannot relabel an old NWS issuance as current.
- Use median daily high/low when source spreads are at most 6°C. On a greater
  spread use NWS temperatures. Condition agreement wins; a tie prefers NWS.
  Condition codes, snow totals and probability values are not blindly averaged:
  retain a coherent set of condition cues from the selected source.
- Aggregate freshness uses the oldest contributor. Keep the historical
  `open_meteo` manifest key for existing images/backups, with explicit sources,
  selected_source, agreement and temperature_spread_c inside its normalized value.
  Settings reports source availability, fetch/issuance times and disagreements.
- The 6°C/18-hour thresholds are conservative operational choices, not calibrated
  forecast skill estimates. Future tuning should compare stored forecasts with
  observed local highs/lows, rather than adding equal-weight sources arbitrarily.

Primary API references:
- https://open-meteo.com/en/docs
- https://www.weather.gov/documentation/services-web-api

## Verification matrix

- Automated route/link/asset/unique-ID checks for Overview, Appearance, Special
  days, Artwork library, Device health, Settings and Recovery with empty and
  populated registries, multiple frames, delivered/prepared images and special days.
- Settings save, failed validation without mutation, event-art upload/assignment,
  unknown/deleted frames, missing previews, optional corrupt status, unavailable
  backup metadata, and bad-CSRF rejection across every management mutation.
- Provider outage/recovery, HTTP 429/500/503, malformed JSON/schema, units, DST,
  wrong date, stale/future issuance, partial daylight, source disagreement,
  conservative aggregate freshness, fetch windows and bounded daily weather retry.
- Real Chromium: all seven pages at 320, 390 and 1280 pixels, no overflow, visible
  broken images, duplicate IDs, inline scripts or JavaScript errors. Saved event
  switch survives reload; injected transport failure restores the switch and
  provides an explicit unconfirmed-save remedy. Expired sessions remain guarded.
- All seven pages load against a private offline clone of the actual verified
  production backup. Providers and rendering are disabled during that rehearsal.
- Existing 117 USB browser/controller/transport simulations cover wrong hardware,
  unsupported browser, busy firmware, cancellation, disconnect/reconnect, timeouts,
  interrupted writes, hashes, lease/session conflicts, expired authentication,
  settings restoration, cloud proof, display failure and completion retries.

The USB simulations do not qualify native browser permission dialogs, electrical
reset timing, a real flash, or the physical panel. A gift still needs a supervised
recovery and overnight wake check on the actual frame. Production page checks and
healthy containers are separate evidence from those physical acceptance steps.

## Deployment and rollback

Before deployment, create and verify `pre-management-weather-20261020`, copy it
independently off the server, and retain a private compose/release/image rollback
snapshot outside the application backup directory. Deploy only the Emviary service.
Verify frame credential/policy invariants and unrelated container start times.
Confirm health/version, management pages, source snapshots and browser console.
