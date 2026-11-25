# Research and implementation records

Use [README](../README.md), [RUNBOOK](../RUNBOOK.md) and
[deployment guidance](../DEPLOYMENT.md) for current operation. These reports
retain their original versions, measurements, design alternatives and physical
acceptance limits. An old statement such as “current deployment” is scoped to
its recorded review, not a claim about today’s host or device.

## Protocol and behavior references

- [Offline cache contract](OFFLINE_CACHE_CONTRACT.md): capability-gated neutral tiles.
- [Display history](DISPLAY_HISTORY.md): prepared, sent and device-reported evidence.
- [Forecast freshness](REFRESH_FRESHNESS.md): scheduled and button preparation.
- [Wi-Fi staging](WIFI_STAGING.md): saved profiles and historical acceptance.
- [Artwork deletion](ARTWORK_DELETION.md): recoverable owner exclusions/deletion.

Current gift lifecycle code is in `src/emviary/gift_mode.py` and `gift_routes.py`.
The owner procedure is in RUNBOOK. Gift welcome is separate from the older
[gift-readiness assessment](GIFT_READINESS_PLAN_2026_10_13.md). Corrected gift
basic firmware support starts at v0.8.13; Ready to wrap and power-on reveal require
v0.8.15 with gift capability 2. Release/build success does not establish installation
or complete switched-off/offline/physical qualification.

## Complete index

| Record | Scope |
| --- | --- |
| [Artwork library deletion](ARTWORK_DELETION.md) | Historical design, implementation or acceptance evidence; dates retained. |
| [Bird artwork research and source audit](ART_SOURCES_2026-10.md) | Historical design, implementation or acceptance evidence; dates retained. |
| [Colorado artwork expansion](COLORADO_ART.md) | Historical design, implementation or acceptance evidence; dates retained. |
| [Composition flow review](COMPOSITION_FLOW_REVIEW_2026_10_16.md) | Historical design, implementation or acceptance evidence; dates retained. |
| [Display blanking investigation, 2026-10-08](DISPLAY_DIAGNOSTICS.md) | Historical design, implementation or acceptance evidence; dates retained. |
| [Display history evidence](DISPLAY_HISTORY.md) | Historical design, implementation or acceptance evidence; dates retained. |
| [Emviary migration](EMVIARY_MIGRATION.md) | Historical design, implementation or acceptance evidence; dates retained. |
| [Polished frame status, firmware v0.8.8](FRAME_STATUS_2026_10_13.md) | Historical design, implementation or acceptance evidence; dates retained. |
| [Emviary gift readiness](GIFT_READINESS_PLAN_2026_10_13.md) | Historical design, implementation or acceptance evidence; dates retained. |
| [Guided USB recovery](GUIDED_USB_RECOVERY_2026_10.md) | Historical design, implementation or acceptance evidence; dates retained. |
| [Emviary health check, October 28, 2026](HEALTH_CHECK_2026_10_28.md) | Historical design, implementation or acceptance evidence; dates retained. |
| [Health findings remediation, November 6, 2026](HEALTH_FIXES_2026_11_06.md) | Historical design, implementation or acceptance evidence; dates retained. |
| [Implemented POC, 2026-10-08](IMPLEMENTATION.md) | Historical design, implementation or acceptance evidence; dates retained. |
| [Management simplification and USB recovery](MANAGEMENT_SIMPLIFICATION_2026_10.md) | Historical design, implementation or acceptance evidence; dates retained. |
| [Management and weather resilience review](MANAGEMENT_WEATHER_REVIEW_2026_10_20.md) | Historical design, implementation or acceptance evidence; dates retained. |
| [Offline cache response contract v1](OFFLINE_CACHE_CONTRACT.md) | Protocol reference with dated implementation evidence. |
| [Weather-safe offline rotation implementation](OFFLINE_ROTATION_IMPLEMENTATION_2026_10_13.md) | Historical design, implementation or acceptance evidence; dates retained. |
| [Offline rotation proposal](OFFLINE_ROTATION_PLAN.md) | Historical design, implementation or acceptance evidence; dates retained. |
| [E1002 picture-quality audit, 2026-10-08](PICTURE_QUALITY.md) | Historical design, implementation or acceptance evidence; dates retained. |
| [Upstream projects and reuse](PROJECTS.md) | Historical design, implementation or acceptance evidence; dates retained. |
| [Recovery and management status resilience](RECOVERY_RESILIENCE_REVIEW_2026_10_19.md) | Historical design, implementation or acceptance evidence; dates retained. |
| [Recovery verification hardening, 2026-10-13](RECOVERY_VERIFICATION_HARDENING_2026_10_13.md) | Historical design, implementation or acceptance evidence; dates retained. |
| [Prepared images and forecast freshness](REFRESH_FRESHNESS.md) | Historical design, implementation or acceptance evidence; dates retained. |
| [Related bird-frame projects: review and incorporated artwork](RELATED_PROJECTS.md) | Historical design, implementation or acceptance evidence; dates retained. |
| [Reliability and collection upgrades, October 12, 2026](RELIABILITY_UPGRADES.md) | Historical design, implementation or acceptance evidence; dates retained. |
| [Browser USB recovery hardware acceptance](USB_RECOVERY_HARDWARE_2026_10_12.md) | Historical design, implementation or acceptance evidence; dates retained. |
| [Guided USB recovery implementation](USB_RECOVERY_IMPLEMENTATION_2026_10_12.md) | Historical design, implementation or acceptance evidence; dates retained. |
| [Emviary USB recovery reliability plan](USB_RECOVERY_RELIABILITY_PLAN_2026_10_12.md) | Historical design, implementation or acceptance evidence; dates retained. |
| [Review of the five suggested artwork sources](USER_ART_SOURCES_2026-10.md) | Historical design, implementation or acceptance evidence; dates retained. |
| [Emviary 0.12.1 experience and service review](UX_REVIEW_2026_10.md) | Historical design, implementation or acceptance evidence; dates retained. |
| [Saved Wi-Fi staging](WIFI_STAGING.md) | Historical design, implementation or acceptance evidence; dates retained. |
| [Emviary E1002 firmware audit and release evidence](firmware-resource-audit-2026-10-08.md) | Historical design, implementation or acceptance evidence; dates retained. |
| [Memory optimization, 2026-10-12](memory-optimization-2026-10-12.md) | Historical design, implementation or acceptance evidence; dates retained. |
