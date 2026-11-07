# Shared host maintenance correction

Deployed November 6, 2026 Denver time. Backup: 05:15; updates: 05:45.
The host schedule-watch.py JOBS mapping must match these times. Preserve its
other source and notification state; activate the new monitoring window at the
schedule transition to avoid retroactive missed-start alerts.

Stop the timers before editing their calendars, reload systemd, verify the next
scheduled times, then start the timers with a future-only first trigger. Check queued jobs as
well as active services during the cutover. Never start the backup or update service
as part of a schedule-only edit. Do not interrupt an active cold snapshot.

The patch handles a queued image that Docker no longer retains: discard only
that unavailable candidate and defer that service, preserving the observation
delay and continuing other checks. Missing running images or daemon failures
remain errors. No registry pull failure is silently ignored. The patch was
applied to live source without unrelated local image-cleanup changes.

Private host rollback: /var/lib/one-maintenance-recovery/20261107T055510Z.
Private application rollback: /docker/backups/emviary-deployments/health-20261106.
Restore only the affected files or Emviary image entry after reviewing newer
changes. Keep application data compatible with any reverted image.
