#!/usr/bin/python3
"""Independent readiness monitor. Never wakes a frame or changes containers."""

import datetime as dt
import importlib.util
import json
from pathlib import Path
import subprocess
import sys
import time

STATE = Path("/var/lib/emviary-watch/status.json")


def fetch():
    # A short preparation lock or container restart must not create an alert.
    for attempt in range(3):
        try:
            result = subprocess.run(
                ["docker", "exec", "emviary", "emviary", "readiness"],
                capture_output=True,
                text=True,
                timeout=30,
            )
            if result.returncode not in (0, 1):
                raise RuntimeError("readiness command failed")
            report = json.loads(result.stdout)
            if report.get("status") not in ("ready", "attention"):
                raise ValueError("invalid readiness status")
            return report
        except (OSError, ValueError, RuntimeError, subprocess.TimeoutExpired):
            if attempt == 2:
                raise
            time.sleep(10)


def publish(title, message):
    spec = importlib.util.spec_from_file_location("notifier", "/docker/ops/update-notify.py")
    notifier = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(notifier)
    notifier.publish(title, message, priority=2 if title.endswith("recovered") else 4)


def check(path=STATE, get=fetch, send=publish, now=None, dry_run=False):
    now = now or dt.datetime.now(dt.timezone.utc)
    try:
        report = get()
        status = report["status"]
        backups = report["backups"]
        reasons = [
            "backup:" + backups["local_status"],
            "independent:" + backups["independent_status"],
        ]
        reasons += sorted(
            {alert["code"] for frame in report["frames"] for alert in frame["alerts"]}
        )
    except (OSError, RuntimeError, ValueError, KeyError, TypeError, subprocess.TimeoutExpired):
        status, reasons = "unavailable", ["readiness check failed"]
    record = {"status": status, "reasons": reasons, "checked_at": now.isoformat()}
    if dry_run:
        return record
    path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    try:
        previous = json.loads(path.read_text()) if path.exists() else {}
        if not isinstance(previous, dict):
            raise ValueError("invalid monitor state")
        last = (
            dt.datetime.fromisoformat(previous["notified_at"])
            if previous.get("notified_at")
            else None
        )
        if last is not None and (last.tzinfo is None or last > now):
            raise ValueError("invalid notification time")
    except (OSError, ValueError, TypeError):
        previous, last = {}, None
    changed = status != previous.get("status") or reasons != previous.get("reasons")
    alert = status != "ready"
    due = changed or last is None or now - last >= dt.timedelta(days=1)
    if (alert and due) or (status == "ready" and previous.get("status") not in (None, "ready")):
        send(
            "Emviary needs attention" if alert else "Emviary readiness recovered",
            ", ".join(reasons) + ". Review https://emviary.majjix.com/manage/recovery. "
            "Readiness checks do not confirm the physical panel.",
        )
        record["notified_at"] = now.isoformat()
    elif last:
        record["notified_at"] = last.isoformat()
    temp = path.with_suffix(".tmp")
    temp.write_text(json.dumps(record) + "\n")
    temp.chmod(0o600)
    temp.replace(path)
    return record


if __name__ == "__main__":
    print(json.dumps(check(dry_run="--check-only" in sys.argv)))
