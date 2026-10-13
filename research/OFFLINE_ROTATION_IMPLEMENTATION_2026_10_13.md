# Weather-safe offline rotation implementation

Firmware candidate v0.8.9, service candidate 0.16.0. No extra scheduled wakes.

Normal 200 downloads opt in to bounded metadata, preserving legacy EPDGZ bodies and recovery SHA. The backend quantizes a weather-free composition with the production converter and extracts an exact packed header tile. It excludes all special-day artwork/messages. Optional tile preparation failure preserves ordinary image delivery but prevents admission.

The frame verifies complete body SHA and tile bounds/palette before admitting successfully displayed ordinary bird/wildlife compositions. FIFO eviction uses a 16 MiB and 256-entry upper bound while preserving max(4 MiB, 25 percent LittleFS) free plus 256 KiB staging. Playback is circular; old images are not deleted by viewing. Atomic publication, bounded cleanup, verified duplicate repair, newest-fitting index recovery and alternating weather-free snapshots preserve useful art through power loss.

Cron display wakes remain unchanged. Network attempts wait five minutes after the first two failures and 48 hours after three or more; white navigation retains the cooldown, green/power-on explicitly retries. Failed cloud work turns the radio off before cached refresh. Cached-only wakes skip Wi-Fi, time sync and OTA checks. Critical battery (known <=10 percent, no USB, scheduled) holds the picture. Unknown battery values do not cause false critical holds. Short LEFT/RIGHT remain previous/next, long LEFT diagnostics is unchanged.

Season metadata prefers current-season or evergreen art. If all alternatives are unusable, the current known cached ordinary composition can still have its weather removed, then be held rather than cycling stale seasonal art. With no valid cache, retain existing pixels and never blank the panel.

Last cloud success and offline state remain distinct. Offline pixels never claim the original cloud ETag. Cache count/bytes and mode piggyback on normal telemetry. The website identifies the last cloud-confirmed picture and explains that an offline local rotation is not a live mirror. Device health displays compact last-reported cache details.

Validation so far: 254 firmware host tests including real filesystem fault scenarios; local v0.8.9 SDK build passed with 55 percent OTA slot free. Focused backend tests cover exact six-color extraction, all weather differences within the source tile, special-day exclusion, legacy compatibility, optional converter failure and bounded retries. Official firmware CI, full backend suite, deployment, OTA and physical outage acceptance pending.

Battery behavior is verified structurally; charging interval and energy savings are not measured without power equipment. No normal debug logging or full frame backup added.
