# Markdown documentation review, November 24, 2026

## Coverage and boundaries

Reviewed all **61 tracked Markdown files** returned by `git ls-files '*.md'` at
review start. This inventory and `research/README.md` are new audit/navigation
files. AGENTS.md is preserved read-only. RUNBOOK.md, CODEX_HANDOFF.md and the gift-asset README were also reviewed
and reconciled during the final integration.
No firmware-submodule documentation, code, policy, credentials or live settings
were changed by this Markdown pass. No commit or publication is implied.

Evidence came from the current service/workflow/configuration/test source,
tracked catalog/assets and existing dated records. Source was reviewed at the
`92fe0ab` gift implementation stage with integration changes continuing concurrently.
The implementation revision passed 514 CI tests passed at that revision, including 11 gift tests;
firmware 263 host checks and SDK compilation were separately reported. This audit
did not rerun those suites or convert software results into physical acceptance.

## Release and operational evidence

At the review handoff, the maintainer's verified live snapshot was service
`be8bb4c` and installed firmware v0.8.10 with automatic stable updates, a seven-day
delay and no pin. v0.8.12 was published from `1618b7d` but not installed. Corrected
v0.8.13 completed official build run `45502035920` from
`3b5612f0bac2819780acbb9f8b8bb45cadf072f7`; the matching recovery
files were downloaded and hash-verified during final integration. Gift feature metadata
requires that corrected implementation. This does not establish installation. Final publication/deployment evidence
belongs in RUNBOOK and CODEX_HANDOFF, not inferred from this source snapshot.
No gift was armed. Native 800 × 480 proofs and automated checks do not establish
switched-off packing, offline reveal, power cycling or the real panel result.

A fresh local rollout backup was reported verified at
`/downloads2/backups/rollouts/releases/emviary/20261124T221958.070972Z`.
That is distinct from the pre-existing off-host pull failure reported at 14:09;
this documentation pass did not repair it or claim a fresh independent copy.
Manual host commands use `one-codex`. The pull helper still has its own configured
SSH target; changing that source is outside this Markdown-only ownership.

## Per-file disposition

| Original tracked file | Disposition | Evidence and preservation |
| --- | --- | --- |
| [AGENTS.md](../AGENTS.md) | Preserved, read-only | Authoritative project workflow and evidence boundaries; no policy/model/approval rewrite. |
| [ART_DIRECTION.md](../ART_DIRECTION.md) | Updated; versioned history retained | render.py, gift_mode.py and catalog; common-name captions, symmetric layouts and local firmware responsibilities. |
| [CODEX_HANDOFF.md](../CODEX_HANDOFF.md) | Reviewed and reconciled | Current operations, release evidence and remaining physical acceptance are recorded without changing historical evidence. |
| [DEPLOYMENT.md](../DEPLOYMENT.md) | Updated; original spec retained | checks.yml/container.yml, backup-before-home-rollout.sh, Compose example and recovery/gift routes. |
| [PLAN.md](../PLAN.md) | Historical status added | Original October architecture/options retained; current README/RUNBOOK/DEPLOYMENT linked. |
| [PROJECT_STRUCTURE.md](../PROJECT_STRUCTURE.md) | Updated | Tracked repository tree and separate firmware submodule; path-dependent build caches clarified. |
| [README.md](../README.md) | Updated | Service/API/gift/recipient source; current renderer/cache roles, controls, auth, gift v0.8.13 gates, CI and attribution. |
| [RUNBOOK.md](../RUNBOOK.md) | Reviewed and reconciled | Current operations, release evidence and remaining physical acceptance are recorded without changing historical evidence. |
| [UX_REVIEW.md](../UX_REVIEW.md) | Historical status added | October UI findings/measurements retained; no claim of a fresh accessibility certification. |
| [art/COLORADO-ATTRIBUTION.md](../art/COLORADO-ATTRIBUTION.md) | Reviewed, retained | Original plate/source snapshot credits preserved; catalog and local attribution references checked. |
| [art/COLORADO-BIRD-COVERAGE.md](../art/COLORADO-BIRD-COVERAGE.md) | Historical status added | Recorded November expansion and source citations retained; catalog/current owner exclusions are authoritative. |
| [art/FUGLERAMME-ATTRIBUTION.md](../art/FUGLERAMME-ATTRIBUTION.md) | Reviewed, retained | Imported upstream context clarified; licensing/source credits preserved without relicensing. |
| [art/occasions/README.md](../art/occasions/README.md) | Updated provenance scope | Source manifest/27-asset collection and installer; recorded enablement distinguished from current owner state. |
| [art/provenance/ai-color-cutouts/README.md](../art/provenance/ai-color-cutouts/README.md) | Updated review wording | Original63-species prompts/manifests retained; saved review settings distinguished from current device settings. |
| [art/provenance/rocket.md](../art/provenance/rocket.md) | Reviewed, retained | Catalog four-pose portrait identity/provenance; private photos and physical gap retained. |
| [art/provenance/special-scenes.md](../art/provenance/special-scenes.md) | Reviewed, retained | Tracked season/memory scene assets; AI/personal-place boundaries unchanged. |
| [art/wildlife/README.md](../art/wildlife/README.md) | Updated provenance scope | Catalog and expansion manifests; original counts historical; Rocket link added without physical claims. |
| [deployment/CONTAINER_REGISTRY.md](../deployment/CONTAINER_REGISTRY.md) | Reviewed, retained | container.yml matches checked-main gate, immutable tags/digest, latest promotion and publication/deployment separation. |
| [deployment/TRUSTED_NETWORK_ACCESS.md](../deployment/TRUSTED_NETWORK_ACCESS.md) | Updated | trusted_network.py and authenticated API/gift contacts; explicit home-LAN scope and gift-safe renewal instructions. |
| [deployment/host-maintenance/README.md](../deployment/host-maintenance/README.md) | Historical status added | November 6 intervention and rollback paths retained; actual current timers must be inspected. |
| [deployment/owner-oidc.md](../deployment/owner-oidc.md) | Reviewed, retained | owner_oidc.py, owner session/auth source and existing environment contract. |
| [docs/BATTERY_RESULTS.md](../docs/BATTERY_RESULTS.md) | Reviewed, retained | Dated November 23 measured snapshot and estimator limits; no reinterpretation as completed endurance. |
| [docs/FRAME_GALLERY.md](../docs/FRAME_GALLERY.md) | Updated | Tracked showcase assets/prompts/compositions checked; concise battery copy and image labels aligned with the public design. |
| [docs/SPECIAL_DAYS_GALLERY.md](../docs/SPECIAL_DAYS_GALLERY.md) | Reviewed, retained | Tracked special-day image assets and public collection; not an enablement or physical-device claim. |
| [experiments/PROVENANCE.md](../experiments/PROVENANCE.md) | Updated | Quarantined experiments distinguished from approved generated collections; exact historical prompts retained. |
| [research/ARTWORK_DELETION.md](../research/ARTWORK_DELETION.md) | Historical/reference context updated | Historical report retained; current-status/backlink added. Recorded test counts, release IDs, physical results and source citations not promoted to fresh evidence. |
| [research/ART_SOURCES_2026-10.md](../research/ART_SOURCES_2026-10.md) | Historical/reference context updated | Historical report retained; current-status/backlink added. Recorded test counts, release IDs, physical results and source citations not promoted to fresh evidence. |
| [research/COLORADO_ART.md](../research/COLORADO_ART.md) | Historical/reference context updated | Historical report retained; current-status/backlink added. Recorded test counts, release IDs, physical results and source citations not promoted to fresh evidence. |
| [research/COMPOSITION_FLOW_REVIEW_2026_10_16.md](../research/COMPOSITION_FLOW_REVIEW_2026_10_16.md) | Historical/reference context updated | Historical report retained; current-status/backlink added. Recorded test counts, release IDs, physical results and source citations not promoted to fresh evidence. |
| [research/DISPLAY_DIAGNOSTICS.md](../research/DISPLAY_DIAGNOSTICS.md) | Historical/reference context updated | Historical report retained; current-status/backlink added. Recorded test counts, release IDs, physical results and source citations not promoted to fresh evidence. |
| [research/DISPLAY_HISTORY.md](../research/DISPLAY_HISTORY.md) | Historical/reference context updated | Historical report retained; current-status/backlink added. Recorded test counts, release IDs, physical results and source citations not promoted to fresh evidence. |
| [research/EMVIARY_MIGRATION.md](../research/EMVIARY_MIGRATION.md) | Historical/reference context updated | Historical report retained; current-status/backlink added. Recorded test counts, release IDs, physical results and source citations not promoted to fresh evidence. |
| [research/FRAME_STATUS_2026_10_13.md](../research/FRAME_STATUS_2026_10_13.md) | Historical/reference context updated | Historical report retained; current-status/backlink added. Recorded test counts, release IDs, physical results and source citations not promoted to fresh evidence. |
| [research/GIFT_READINESS_PLAN_2026_10_13.md](../research/GIFT_READINESS_PLAN_2026_10_13.md) | Historical/reference context updated | Historical report retained; current-status/backlink added. Recorded test counts, release IDs, physical results and source citations not promoted to fresh evidence. |
| [research/GUIDED_USB_RECOVERY_2026_10.md](../research/GUIDED_USB_RECOVERY_2026_10.md) | Historical/reference context updated | Historical report retained; current-status/backlink added. Recorded test counts, release IDs, physical results and source citations not promoted to fresh evidence. |
| [research/HEALTH_CHECK_2026_10_28.md](../research/HEALTH_CHECK_2026_10_28.md) | Historical/reference context updated | Historical report retained; current-status/backlink added. Recorded test counts, release IDs, physical results and source citations not promoted to fresh evidence. |
| [research/HEALTH_FIXES_2026_11_06.md](../research/HEALTH_FIXES_2026_11_06.md) | Historical/reference context updated | Historical report retained; current-status/backlink added. Recorded test counts, release IDs, physical results and source citations not promoted to fresh evidence. |
| [research/IMPLEMENTATION.md](../research/IMPLEMENTATION.md) | Historical/reference context updated | Historical report retained; current-status/backlink added. Recorded test counts, release IDs, physical results and source citations not promoted to fresh evidence. |
| [research/MANAGEMENT_SIMPLIFICATION_2026_10.md](../research/MANAGEMENT_SIMPLIFICATION_2026_10.md) | Historical/reference context updated | Historical report retained; current-status/backlink added. Recorded test counts, release IDs, physical results and source citations not promoted to fresh evidence. |
| [research/MANAGEMENT_WEATHER_REVIEW_2026_10_20.md](../research/MANAGEMENT_WEATHER_REVIEW_2026_10_20.md) | Historical/reference context updated | Historical report retained; current-status/backlink added. Recorded test counts, release IDs, physical results and source citations not promoted to fresh evidence. |
| [research/OFFLINE_CACHE_CONTRACT.md](../research/OFFLINE_CACHE_CONTRACT.md) | Historical/reference context updated | offline_cache.py/firmware contract reviewed; wire bounds retained, source path and current-operations context added. |
| [research/OFFLINE_ROTATION_IMPLEMENTATION_2026_10_13.md](../research/OFFLINE_ROTATION_IMPLEMENTATION_2026_10_13.md) | Historical/reference context updated | Historical report retained; current-status/backlink added. Recorded test counts, release IDs, physical results and source citations not promoted to fresh evidence. |
| [research/OFFLINE_ROTATION_PLAN.md](../research/OFFLINE_ROTATION_PLAN.md) | Historical/reference context updated | Historical report retained; current-status/backlink added. Recorded test counts, release IDs, physical results and source citations not promoted to fresh evidence. |
| [research/PICTURE_QUALITY.md](../research/PICTURE_QUALITY.md) | Historical/reference context updated | Historical report retained; current-status/backlink added. Recorded test counts, release IDs, physical results and source citations not promoted to fresh evidence. |
| [research/PROJECTS.md](../research/PROJECTS.md) | Historical/reference context updated | Historical report retained; current-status/backlink added. Recorded test counts, release IDs, physical results and source citations not promoted to fresh evidence. |
| [research/RECOVERY_RESILIENCE_REVIEW_2026_10_19.md](../research/RECOVERY_RESILIENCE_REVIEW_2026_10_19.md) | Historical/reference context updated | Historical report retained; current-status/backlink added. Recorded test counts, release IDs, physical results and source citations not promoted to fresh evidence. |
| [research/RECOVERY_VERIFICATION_HARDENING_2026_10_13.md](../research/RECOVERY_VERIFICATION_HARDENING_2026_10_13.md) | Historical/reference context updated | Historical report retained; current-status/backlink added. Recorded test counts, release IDs, physical results and source citations not promoted to fresh evidence. |
| [research/REFRESH_FRESHNESS.md](../research/REFRESH_FRESHNESS.md) | Historical/reference context updated | service scheduling/source contract reviewed;03:15 example explicitly dated instead of claiming current schedule. |
| [research/RELATED_PROJECTS.md](../research/RELATED_PROJECTS.md) | Historical/reference context updated | Historical report retained; current-status/backlink added. Recorded test counts, release IDs, physical results and source citations not promoted to fresh evidence. |
| [research/RELIABILITY_UPGRADES.md](../research/RELIABILITY_UPGRADES.md) | Historical/reference context updated | Historical report retained; current-status/backlink added. Recorded test counts, release IDs, physical results and source citations not promoted to fresh evidence. |
| [research/USB_RECOVERY_HARDWARE_2026_10_12.md](../research/USB_RECOVERY_HARDWARE_2026_10_12.md) | Historical/reference context updated | Historical report retained; current-status/backlink added. Recorded test counts, release IDs, physical results and source citations not promoted to fresh evidence. |
| [research/USB_RECOVERY_IMPLEMENTATION_2026_10_12.md](../research/USB_RECOVERY_IMPLEMENTATION_2026_10_12.md) | Historical/reference context updated | Historical report retained; current-status/backlink added. Recorded test counts, release IDs, physical results and source citations not promoted to fresh evidence. |
| [research/USB_RECOVERY_RELIABILITY_PLAN_2026_10_12.md](../research/USB_RECOVERY_RELIABILITY_PLAN_2026_10_12.md) | Historical/reference context updated | Historical report retained; current-status/backlink added. Recorded test counts, release IDs, physical results and source citations not promoted to fresh evidence. |
| [research/USER_ART_SOURCES_2026-10.md](../research/USER_ART_SOURCES_2026-10.md) | Historical/reference context updated | Historical report retained; current-status/backlink added. Recorded test counts, release IDs, physical results and source citations not promoted to fresh evidence. |
| [research/UX_REVIEW_2026_10.md](../research/UX_REVIEW_2026_10.md) | Historical/reference context updated | Historical report retained; current-status/backlink added. Recorded test counts, release IDs, physical results and source citations not promoted to fresh evidence. |
| [research/WIFI_STAGING.md](../research/WIFI_STAGING.md) | Historical/reference context updated | Historical report retained; current-status/backlink added. Recorded test counts, release IDs, physical results and source citations not promoted to fresh evidence. |
| [research/firmware-resource-audit-2026-10-08.md](../research/firmware-resource-audit-2026-10-08.md) | Historical/reference context updated | Historical report retained; current-status/backlink added. Recorded test counts, release IDs, physical results and source citations not promoted to fresh evidence. |
| [research/memory-optimization-2026-10-12.md](../research/memory-optimization-2026-10-12.md) | Historical/reference context updated | Historical report retained; current-status/backlink added. Recorded test counts, release IDs, physical results and source citations not promoted to fresh evidence. |
| [src/emviary/gift_assets/README.md](../src/emviary/gift_assets/README.md) | Reviewed and reconciled | Current operations, release evidence and remaining physical acceptance are recorded without changing historical evidence. |
| [tools/BACKUPS.md](../tools/BACKUPS.md) | Updated | pull_verified_backup.py, backup_validation.py, LaunchAgent and rollout script; independent/local distinction and no false repair claim. |
| [web-recovery/README.md](../web-recovery/README.md) | Updated | package_usb_recovery.py, recovery source/package manifest; release-version placeholder and matching13 gate. |

## Verification and remaining follow-up

Local Markdown targets, tracked asset references, current command flags and
workflow names were checked. Historical dates, test counts, energy/resource
measurements, accepted defects and physical limitations remain historical.
Attribution, licenses, prompt records and source provenance were preserved.
No external-link availability or fresh host/device inspection is claimed.

Release follow-up: record actual rollout evidence and retain the independent-backup failure until it
is fixed and freshly verified. The Compose fragment retains an old local image
and example proxy configuration, now prominently identified as an inherited
structural example in DEPLOYMENT rather than current production settings.

## Completed release verification

PR #36 merged as `17214900d5ec602f39e2112a94ea7f66aadd8fda`. Final PR/main checks
passed 514 service tests, lint/format and recovery checks. The checked container
was published and deployed as digest
`sha256:65fba36e5d5dcf26b8873eeb2b8d4564d7f90dee8a7b25e963379a400243317d`.
Live health, protected gift access, cookie-free home-network management, and
desktop/390 px mobile controls passed. Firmware v0.8.13 and its matching recovery
assets are published; the installed frame remains v0.8.10 under its unchanged
stable/seven-day policy. Zero production gift packages exist. Physical acceptance
and the independent-backup failure remain open, as detailed in CODEX_HANDOFF.
