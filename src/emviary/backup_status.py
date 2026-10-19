"""Read backup completion evidence without making recovery depend on filesystem health."""

import json
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


def backup_health(backup_dir, data_dir):
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
    return {
        "latest_verified": max(verified).isoformat() if verified else None,
        "unreadable": unreadable,
        "listing_unavailable": listing_unavailable,
        "independent": independent.isoformat() if independent else None,
        "independent_unavailable": independent_unavailable,
    }


def backup_health_section(service, escape, local_time):
    health = backup_health(service.settings.backup_dir, service.settings.data_dir)
    body = '<section class="card"><h2>Backup health</h2>'
    if health["latest_verified"]:
        body += (
            "<p>Latest verified backup: "
            + escape(local_time(health["latest_verified"]))
            + ". New backups pass an isolated offline restore rehearsal.</p>"
        )
    elif not health["listing_unavailable"]:
        body += '<p class="notice">No readable backup with a verified restore rehearsal yet.</p>'
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
    return (
        body + '<p class="quiet">Backups without a completion record '
        "are not listed as verified.</p></section>"
    )
