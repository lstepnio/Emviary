"""Read-only operational evidence shared by the owner endpoint and host monitor."""

from .backup_status import backup_health
from .diagnostics import management_alerts


def readiness_summary(service):
    now = service.clock()
    backups = backup_health(service.settings.backup_dir, service.settings.data_dir, now)
    frames = [
        {
            "id": frame["id"],
            "alerts": [
                {"code": code, "title": title, "detail": detail}
                for code, title, detail in management_alerts(service, frame, now)
            ],
        }
        for frame in service.store.frames()
    ]
    ready = (
        backups["local_status"] == "fresh"
        and backups["independent_status"] == "fresh"
        and not backups["unreadable"]
        and all(not frame["alerts"] for frame in frames)
    )
    return {
        "status": "ready" if ready else "attention",
        "checked_at": now.isoformat(),
        "backups": backups,
        "frames": frames,
    }
