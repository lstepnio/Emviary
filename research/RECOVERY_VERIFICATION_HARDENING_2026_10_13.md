# Recovery verification hardening, 2026-10-13

## Observed problem

Service 0.15.5 and firmware v0.8.7 produced valid correlated boot, image and panel acknowledgments. A later session, created at 14:20 UTC, reached panel completion at 14:23 UTC but remained active after repeated finish attempts. A visible picture is positive panel evidence, not proof that the browser's complete recovery flow finishes reliably.

## Confirmed source defects

- Recovery closed the serial bridge immediately before the physical-picture prompt. Reopening it to finish can restart this bridge/frame combination and invalidate the earlier boot.
- The finish operation had a five-second outer timeout covering a four-second HELLO reply, a four-second END reply and an owner HTTP request with a ten-second budget.
- Delayed cloud acknowledgment was treated as a failed picture pipeline, causing another BEGIN rather than waiting for the existing proof.
- The backend required a panel checkpoint to complete, but did not independently require all correlated boot, cloud, image and identity fields at completion.

## Required behavior

Keep the same USB connection through picture confirmation, renew its temporary lease, and immediately show finishing progress with duplicate confirmation presses disabled. Distinguish pending cloud evidence from device pipeline failure, and poll pending evidence within the existing bounded connection deadline. Finalize only the verified boot and picture; preserve verification if the completion response is lost and reconcile the durable server state. Release USB ownership on finish, cancellation or disconnect. A changed boot must be verified again, never accepted from stale proof.

The backend exposes pending, failed and verified evidence states and independently validates complete proof before accepting physical confirmation. Recovery remains quiet during normal frame operation; monitoring reads existing cloud records only.

## Monitoring

A thread heartbeat checks stored recovery checkpoints and service health every five minutes for 24 hours (288 runs). It looks for unfinished finish attempts, repeated deliveries during cloud verification, stale proofs and stuck leases. It does not open serial ports, wake the frame, initiate recovery or alter firmware/settings.

## Validation

282 backend tests pass, including incomplete-proof rejection, explicit failure state, successful same-picture retry, and idempotent completion. 117 full browser/controller tests passed, including serial ownership, delayed cloud confirmation, lost completion response, changed boot/image proof, idle disconnect and reconnection, heartbeat serialization, and an operation longer than the former finish timeout. Live end-to-end completion is pending the candidate service 0.15.6 deployment. Firmware remains v0.8.7.
