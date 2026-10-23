# Display history evidence

The previous gallery listed generated renders in decreasing image ID order. A
weather revision or refilled queue could therefore appear in Past compositions
without ever reaching the frame. This was not a record of panel refreshes.

Version 0.19 separates three states:

* Prepared: a server render or planned preview. These appear under Coming up,
  Daily refresh or Next button, never as past displays on that evidence alone.
* Sent: a completed authenticated image HTTP response. The transfer ledger records
  the image, digest, response status and server time. A 304 records a response
  without claiming a body transfer or a new panel refresh.
* Frame reported: positive authenticated evidence about an earlier successful
  refresh. Only this ledger feeds Past compositions. Captions show when the
  report arrived, not an invented panel-refresh timestamp.

## Device contract

The audited v0.8.10 firmware persists its image ETag only after successful panel
refresh (`firmware/main/utils.c`, `fetch_display_file`/stream completion). Its
cache cursor is admitted after successful cloud display and advanced after
successful offline display (`offline_cache.c`). Requests contain previous-operation
metrics, so response N cannot confirm the picture it is currently sending.

A positive cloud report requires success/unchanged, HTTP 200/304 and offline mode
false. A strict persisted ETag resolves the image, checked against the cache cursor
when present. An offline report requires offline mode true and a positive rotation
count. It may accompany failed cloud metrics because offline fallback can succeed
when the network fails. Unknown firmware contracts, contradictory hashes,
future renders, unknown images and cross-frame references do not qualify.

USB recovery supplies a stronger explicit panel_refreshed acknowledgment. This
records a display only after existing session, nonce, firmware, device, boot,
image-hash and prior image_verified validation. Repeated acknowledgments do not
create duplicate recovery entries. Receiving or verifying bytes alone is insufficient.

## Migration and gaps

At startup, a single transactional, idempotent migration imports qualifying saved
v0.8.10 cache reports. Neither max-delivered ID nor generated-image ordering is
used as display evidence. Older records, unsupported firmware and intermediate
offline rotations can remain unknown. Device reports are evidence from firmware,
not independent optical proof of what the panel showed.

History groups weather revisions by semantic composition, orders by report arrival,
respects hidden images and skips missing previews. Image pruning keeps ledger
hashes/times with a null image reference; it does not invent replacement artwork.
Backups preserve both ledgers. Existing retention still limits available previews.
No device credentials, Wi-Fi settings or firmware are changed by this migration.

## Verification

Tests cover HTTP fetch then delayed confirmation, unconsumed refills, 304 responses,
failed/missing/contradictory reports, unsupported firmware, offline fallback,
unauthenticated access, cross-frame IDs, preview-only visits, current fetch failure,
restarts, legacy import, report ordering, recovery acknowledgment, backup restore,
pruning, hidden images and query plans without sorting large manifests in /tmp.

An isolated copy of the Oct 23 production database recovered 16 positive reports,
including fox image 346, with zero confirmations for raccoon renders 347 through
357. This is historical device evidence, not a new physical frame test.
