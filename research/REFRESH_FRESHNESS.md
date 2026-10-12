# Prepared images and forecast freshness

## Contract

The server keeps immutable, compressed panel images in two durable slots per
frame. The frame still makes one authenticated cached download on wake. Nothing
on the image request path calls a weather provider or composes/converts artwork.
The current panel palette, processing preset, dithering and image quality are
unchanged. No firmware update or extra device wake is required.

- **Daily refresh:** the default `latest` request prefers a same-local-day image
  prepared in the scheduled cycle, with the current configuration and a fresh
  forecast. Its job and completion record are separate from button preparation.
  An image prepared earlier in the day cannot satisfy this cycle.
- **Next button:** uses the navigation slot at the newest end of the collection.
  After delivery, one successor is prepared after the HTTP body has been sent.
  Expired unconsumed buffers are refreshed proactively by the server scheduler,
  keeping their selected birds, pose, layout and seed when only weather ages.
- **History:** Previous and forward navigation back through saved history return
  the original immutable image, including its original forecast. They never
  rewrite the image being reviewed.
- **Special-day test:** an explicit current-day preview remains available to the
  frame ahead of the ordinary scheduled slot, subject to freshness validation.
- **Public mirror:** continues to use last-delivered bytes, not either ready slot.

## Timing and fallback

`weather_max_age_minutes` defaults to 120, with owner settings allowing 15 to
1440 minutes. Forecast cache entries require the correct local day, location
scope, receipt timestamp and age. The daily cycle requires a snapshot received
at or after its preparation deadline, even if an earlier snapshot is inside
its ordinary age limit. Same-day weather provider failure does not reuse an
expired forecast. Bird presence cache behavior is unchanged.

Emily's normal deadline stays 02:30 America/Denver for a 03:15 wake. If an owner
moves preparation too far before wake, the effective deadline moves into the
last 45 minutes before wake, or half the forecast age limit when shorter.
The site timezone handles daylight saving changes. The scheduler checks every
60 seconds. It also refreshes stale navigation buffers while the frame sleeps.

On a provider outage, rendering can produce same-day artwork without weather.
If no suitable cached image exists, the service returns 304 for a recognized
client image and keeps that picture on the panel. The configuration header is
still included. Without a recognized cursor, it returns 503 with Retry-After
300. It queues backend work rather than holding the frame awake for rendering.
No immediate extra wake is requested.

Preparation failures retry at least 15 minutes apart, at most three times per
local day/configuration episode for each queue. Retry counters and slots survive
restarts. New configuration and new local dates reset the appropriate budget.
A failed/expired render plan gets refreshed weather before eventual publication.
Removed images cannot satisfy a slot or reappear as new images.

## Management and storage

Overview shows On the frame, Daily refresh and Next button independently, with
local dates and forecast receipt times. Appearance contains Forecast freshness.
Schema 6 adds prepared_slots and a delivered-image watermark. Migration preserves
frames, tokens, policies, Wi-Fi profiles, history, battery samples, art deletion
records and current displayed bytes. Scheduled slot images are protected from
history pruning. Original read-only artwork remains unchanged.

## Verification

Automated tests cover early navigation versus the daily cycle, forced forecast
refresh at the daily deadline, post-delivery successor preparation, immutable
public mirror/history, midnight, forecast expiry, weather-free outage fallback,
request-path no-render/no-provider behavior, 304 retention, bounded retries and
restart recovery, interrupted slot publication, configuration changes, Denver
DST transitions, owner authentication/previews and freshness setting bounds.

Actual battery savings need a measured discharge cycle. This change avoids
adding frame wake-ups or synchronous rendering waits; it does increase server
preparation work as weather ages.
