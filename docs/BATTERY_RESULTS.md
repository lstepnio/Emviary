# Early battery results

**The observed unplugged trend projects more than a year to the 20% recharge threshold.** This is an encouraging early result, not a completed year-long endurance test or a guaranteed battery-life specification.

## What was measured

Snapshot checked November 23, 2026 (Mountain time), using the existing production battery history and installed estimator. Reading the history did not wake the frame or change its schedule.

| Observation | Result |
| --- | --- |
| Current uninterrupted battery-only observation window | 41.1 days |
| Reported charge at start of window | 98% |
| Latest reported charge | 92% |
| Change | 6 percentage points |
| Readings in the window | 50 samples on 42 distinct UTC days |
| First reading in the window | October 13, 2026, 23:44 UTC |
| Latest reading | November 24, 2026, 00:59 UTC (November 23 in Colorado) |
| Latest power state | Battery only; not charging; USB disconnected |
| Estimator result | Over one year at the recent rate |
| Estimator confidence | Limited |

The window starts at the first qualifying observation, not necessarily the moment the charger was disconnected. Percentages are device-reported estimates, not measured remaining energy in watt-hours. The projection concerns the time from the latest reading to the 20% recharge threshold, not discharge to zero.

## How the projection works

The installed estimator separates unplugged cycles at charging/USB readings, unexplained increases larger than five percentage points, or contact gaps longer than three days. It keeps the latest reading per UTC day so extra wake-ups do not masquerade as more days of evidence.

It takes the median of pairwise daily discharge slopes, checks variability, and extrapolates toward the 20% recharge threshold. An estimate above 365 days is deliberately presented as “Over one year at the recent rate,” with limited confidence and no precise day count. Stale, flat, noisy, or insufficient observations cannot produce a current projection.

This snapshot was evaluated by the production `emviary:battery-estimate-20261120` image. Its battery module SHA-256 is `e25186aed9ccbf444a2fe6f3dd0b26f0a8c8f910158ab9503ea48e1e2b20badd`. The installed estimator includes the previously deployed slow-trend eligibility correction; this showcase change does not alter battery estimation or firmware.

## What could change the conclusion

Only a small portion of the discharge curve has been observed. Reported percentage can be nonlinear, and temperature, Wi-Fi conditions, manual refreshes, firmware updates and future usage can change consumption. A longer battery-only run spanning substantially more of the discharge curve is needed to establish actual endurance.

The public website presents this dated evidence snapshot. The private management battery page remains the place to inspect current readings and trend status. No year-long physical endurance result is claimed.
