# Offline rotation proposal

Status: accepted proposal, now implemented. See OFFLINE_ROTATION_IMPLEMENTATION_2026_10_13.md for release validation and adjustments found during hardware testing.

## Product behavior

Keep the configured nightly wake. When a bounded cloud attempt fails, display the next valid cached ordinary composition and return to sleep. Offline compositions contain bird or Colorado wildlife art, but never special-day artwork, dates or messages. Hide the forecast, weather icon and temperature entirely in offline mode. Do not invent fresh weather from an expired forecast.

FIFO describes eviction: remove the oldest admitted eligible composition when space is needed. Playback traverses the retained set oldest to newest, then wraps; viewing an image does not delete it. Skip the currently displayed composition when alternatives exist. Right advances and left goes back locally while offline. Five-second LEFT remains diagnostics. If no valid alternative exists, retain the current artwork rather than clear the panel.

## Weather representation

Preferred approach: the backend prepares an exact, palette-quantized replacement tile for every weather-bearing region, along with the ordinary pre-rendered image. The tile restores the background that would occupy that area without the forecast. Store it with the image and apply it in RAM before an offline panel refresh. This is a small bounded pixel copy, not local weather rendering, AI or dithering. Preserve the original cached file and its digest.

The backend owns the composition, tile bounds, background and eligibility rules. A versioned download bundle carries image, small metadata and replacement tile in the normal HTTPS response. Legacy firmware continues receiving its existing EPDGZ representation. All components and lengths are validated before admission. Bind tile and metadata to the exact image hash; never use a guessed rectangle or universally paint it white. Include a backend test that the offline variant contains no weather text, temperatures, icons or forecast-specific artistic cues outside the declared replacement areas.

The strongest simpler alternative is to send a second complete weather-free EPDGZ. It is easier to reason about but duplicates transfer and storage for every image. Keep that as a fallback if the bounded tile cannot preserve the intended art reliably. A stale-weather badge is cheaper but leaves misleading old temperatures visible and is not recommended.

## Cache management

The installed partition layout provides 24.875 MiB of LittleFS, shared with current/staged artwork and other files. Proposed maximum cache budget: 16 MiB, subject to real filesystem usage. Preserve at least max(4 MiB, 25 percent of filesystem capacity) free, plus enough staging space for the largest accepted download. The free-space check must account for non-cache files, the current image and temporary files; this is not a partition resize. OTA slots and NVS are separate and must remain untouched.

A read-only sample of 40 deployed compositions on 2026-10-13 showed median 18,017 bytes, range 8,232 to 55,298 bytes. This suggests substantial capacity, but is not a guaranteed cache count. Bound download sizes, metadata sizes and index processing independently. Govern admission by bytes and available space rather than a promised number of images.

Admit a unique eligible image only after complete body verification and successful display. Do not duplicate repeated 304 responses or button visits. Never admit special-day content. On a special day, retain existing ordinary cache entries without extra fetching to fill the cache. If the current image is a holiday when connectivity fails, replace it with ordinary cached art at the next normal wake.

Use a temporary file, verification and atomic publication. Publish new entries before evicting old ones when space permits. If safe staging is impossible, skip cache admission and preserve the current picture and known-good fallback; do not sacrifice both for a new download. Recover from interrupted downloads, missing index records and corrupt entries without formatting the filesystem. Skip corrupt entries; limit work per wake.

Store only essential durable metadata and admitted image bytes. Persist the playback cursor once after a successful panel refresh, preferably folded into existing durable display-state updates. No flash writes on cache reads, diagnostics, failed network probes or unchanged settings; no normal debug log. RTC state can hold transient retry counters but cannot be the sole cache index because it does not survive complete power loss.

## Scheduling and battery

Separate display_due from network_retry_due. Existing network failure backoff currently affects scheduled wake slots, and URL mode returns to sleep immediately without Wi-Fi. Both paths must be adjusted so offline daily rotation continues while reconnection attempts back off.

Suggested default: one bounded connection/cloud attempt at the usual daily wake. Following repeated failures, limit probes to every 48 hours while still waking to rotate locally each day. Probe all configured networks using the existing bounded selection policy. Turn the radio off as soon as a failed attempt is finished. A cached-only wake performs one decode, tile copy and panel refresh, then sleeps; no SNTP, GitHub update check, local web server or Wi-Fi scan is needed on that path. A manual reconnect action can bypass the retry cooldown. Ordinary offline button navigation uses the cache during that cooldown rather than paying for repeated failed network requests.

Do not add periodic hourly or five-minute wakeups, background cache filling or a separate weather provider on the ESP32. The replacement tile travels with normal downloads. Reconnection restores cloud freshness rules and policy, resets the failure cooldown, and resumes ordinary admission. Do not immediately perform multiple panel refreshes to catch up.

An e-paper refresh still costs energy even without networking. Daily offline rotation prioritizes the requested experience over the lowest possible consumption, which would be retaining one image. Offer a low-battery hold mode that stops scheduled offline changes at the existing critical battery threshold. Quantify duration, network time, bytes and flash operations in tests; do not promise a charging interval without current measurements.

## Seasons and cloud truth

Decorative seasonal motifs are distinct from forecasts. Backend metadata can restrict a composition to its appropriate seasonal window and identify evergreen entries. If the clock is untrusted, use evergreen ordinary art. If no eligible alternative exists, retain the current picture. Do not evaluate holiday rules locally.

During an outage the website cannot know which cached image the frame actually shows. Label its preview as the last cloud-confirmed picture, rather than claiming a live mirror. On the next normal authenticated check-in, report offline mode, actual displayed composition/variant, cache count/bytes, last cloud success and rotations since contact. Diagnostics can show this immediately without a cloud connection. Keep ordinary weather-free cache representations distinct from the cloud image identity used for recovery verification.

## Implementation and acceptance

1. Define backend eligibility metadata and the weather-neutral tile contract, plus capability-gated legacy compatibility.
2. Implement atomic bounded cache admission, FIFO eviction and circular navigation; preserve existing artwork lifecycle and display mutex rules.
3. Separate nightly display scheduling from network cooldown and add cached-only wake behavior.
4. Add compact diagnostics and honest owner-page connectivity/display status, piggybacking on normal check-ins.
5. Test Wi-Fi loss, reachable Wi-Fi with DNS/TLS/cloud failure, interrupted download/publication, full filesystem, corrupt entries, one/zero entries, reboot/power loss, season rollover, holiday outage, offline buttons and reconnect. Verify no stale weather, no holiday cache rotation, no blanking, no repeated panel refresh, preserved OTA/recovery behavior and bounded work.
6. Validate on the physical E1002, first with short temporary test schedules and then overnight. Compare wake duration and transfer/write counts with baseline. Actual battery energy remains unmeasured without suitable equipment.

Recommendation: implement the small weather-neutral replacement tile and byte-budgeted FIFO cache. Keep cached ordinary art useful indefinitely through circular playback, subject to optional seasonal eligibility, without increasing wake frequency.
