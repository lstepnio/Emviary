"""Read backup completion evidence without making recovery depend on filesystem health."""

import json
import os
from datetime import UTC, datetime, timedelta
from pathlib import Path

from .status_data import timestamp


def read_record(path):
    # Status records are small regular files. Never follow backup-folder links.
    if path.is_symlink() or not path.is_file():
        return None
    with path.open() as handle:
        raw = handle.read(65537)
    if len(raw) > 65536:
        raise ValueError("Status record is too large")
    value = json.loads(raw)
    if not isinstance(value, dict):
        raise ValueError("Status record is not an object")
    return value


# Daily backups and daily off-host pulls get a twelve-hour late allowance.
BACKUP_MAX_AGE = timedelta(hours=36)


def backup_health(backup_dir, data_dir, now=None):
    now = now or datetime.now(UTC)
    verified = []
    unreadable = 0
    listing_unavailable = False
    try:
        # Materialize inside the error boundary: iteration itself may raise.
        candidates = list(Path(backup_dir).iterdir())
    except OSError:
        candidates = []
        listing_unavailable = True
    for candidate in candidates:
        try:
            if candidate.is_symlink() or not candidate.is_dir():
                continue
            record = read_record(candidate / "COMPLETE")
            if record is None or record.get("restore_rehearsal") != "passed":
                continue
            created = timestamp(record.get("created_at"))
            if created is None:
                raise ValueError("Backup status has no valid timestamp")
            verified.append(created)
        except (OSError, ValueError):
            unreadable += 1
    independent = None
    independent_unavailable = False
    try:
        record = read_record(Path(data_dir) / "offhost-backup.json")
        if record is not None:
            independent = timestamp(record.get("created_at"))
            if independent is None:
                raise ValueError("Independent status has no valid timestamp")
    except (OSError, ValueError):
        independent_unavailable = True
    independent_attempt = None
    independent_attempt_unavailable = False
    try:
        attempt = read_record(Path(data_dir) / "offhost-backup-attempt.json")
        if attempt is not None:
            attempted_at = timestamp(attempt.get("checked_at"))
            if attempted_at is None or attempt.get("status") not in {"failed", "verified"}:
                raise ValueError("Independent attempt has no valid outcome")
            independent_attempt = {
                "status": attempt["status"],
                "checked_at": attempted_at.isoformat(),
            }
    except (OSError, ValueError):
        independent_attempt_unavailable = True
    writable = os.access(backup_dir, os.W_OK | os.X_OK)
    latest = max(verified) if verified else None

    def freshness(stamp, unavailable):
        if unavailable:
            return "unavailable"
        if stamp is None:
            return "missing"
        if stamp > now + timedelta(minutes=5):
            return "invalid"
        return "stale" if now - stamp >= BACKUP_MAX_AGE else "fresh"

    independent_status = freshness(
        independent, independent_unavailable or independent_attempt_unavailable
    )
    if independent_attempt:
        attempted_at = timestamp(independent_attempt["checked_at"])
        if attempted_at > now + timedelta(minutes=5):
            independent_status = "invalid"
        elif independent_attempt["status"] == "failed" and (
            independent is None or attempted_at > independent
        ):
            independent_status = "failed"
    return {
        "max_age_hours": BACKUP_MAX_AGE.total_seconds() / 3600,
        "local_status": freshness(latest, listing_unavailable) if writable else "unwritable",
        "local_writable": writable,
        "independent_status": independent_status,
        "independent_last_attempt": independent_attempt,
        "independent_attempt_unavailable": independent_attempt_unavailable,
        "latest_verified": max(verified).isoformat() if verified else None,
        "unreadable": unreadable,
        "listing_unavailable": listing_unavailable,
        "independent": independent.isoformat() if independent else None,
        "independent_unavailable": independent_unavailable,
    }


def backup_health_section(service, escape, local_time):
    health = backup_health(service.settings.backup_dir, service.settings.data_dir, service.clock())
    body = '<section class="card"><h2>Backup health</h2>'
    if health["latest_verified"]:
        body += (
            "<p>Latest verified backup: "
            + escape(local_time(health["latest_verified"]))
            + ". New backups pass an isolated offline restore rehearsal.</p>"
        )
    elif not health["listing_unavailable"]:
        body += '<p class="notice">No readable backup with a verified restore rehearsal yet.</p>'
    if not health["local_writable"]:
        body += (
            '<p class="notice">Backup folder is not writable by Emviary. '
            "New local backups cannot be saved until permissions are corrected.</p>"
        )
    if health["local_status"] in {"stale", "invalid"}:
        body += (
            '<p class="notice">'
            + (
                "Verified backup is overdue. No successful backup within the last 36 hours."
                if health["local_status"] == "stale"
                else "Backup completion time is in the future. Check the backup clock."
            )
            + "</p>"
        )
    if health["listing_unavailable"]:
        body += (
            '<p class="notice">Backup status is unavailable. '
            "Stored backups have not been changed.</p>"
        )
    elif health["unreadable"]:
        body += (
            '<p class="notice">Some backup records could not be read. '
            "Other readable, verified backups are still listed.</p>"
        )
    if health["independent"]:
        body += (
            "<p>Independent copy verified: " + escape(local_time(health["independent"])) + ".</p>"
        )
    elif health["independent_unavailable"]:
        body += '<p class="notice">Independent-copy status is unavailable.</p>'
    else:
        body += '<p class="notice">No independent backup copy has been confirmed.</p>'
    if health["independent_attempt_unavailable"]:
        body += '<p class="notice">Independent-copy attempt status is unavailable.</p>'
    if health["independent_status"] == "failed":
        body += (
            '<p class="notice">The latest independent-copy attempt failed. '
            "The last verified copy remains listed above.</p>"
        )
    if health["independent_status"] in {"stale", "invalid"}:
        body += (
            '<p class="notice">'
            + (
                "Independent copy is overdue. No successful verification within the last 36 hours."
                if health["independent_status"] == "stale"
                else "Independent-copy verification time is in the future. Check the backup clock."
            )
            + "</p>"
        )
    return (
        body + '<p class="quiet">Backups without a completion record '
        "are not listed as verified.</p></section>"
    )
