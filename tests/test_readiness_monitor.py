import importlib.util
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest

spec = importlib.util.spec_from_file_location(
    "monitor", Path(__file__).resolve().parents[1] / "deployment/emviary-watch.py"
)
monitor = importlib.util.module_from_spec(spec)
spec.loader.exec_module(monitor)


def report(status="ready"):
    return {
        "status": status,
        "backups": {"local_status": "fresh", "independent_status": "fresh"},
        "frames": [],
    }


def test_failure_deduplicates_repeats_daily_and_recovers(tmp_path):
    path, sent = tmp_path / "state.json", []
    now = datetime(2026, 11, 6, tzinfo=UTC)

    def send(*args):
        sent.append(args)

    def get():
        return report("attention")

    monitor.check(path, get, send, now)
    monitor.check(path, get, send, now + timedelta(minutes=15))
    assert len(sent) == 1
    monitor.check(path, get, send, now + timedelta(days=1))
    assert len(sent) == 2
    monitor.check(path, report, send, now + timedelta(days=1, minutes=15))
    assert "recovered" in sent[-1][0]
    assert path.stat().st_mode & 0o777 == 0o600


def test_unavailable_and_notification_failure_are_retried(tmp_path):
    path = tmp_path / "state.json"

    def unavailable():
        raise RuntimeError("private details")

    def failed(*args):
        raise RuntimeError("offline")

    with pytest.raises(RuntimeError):
        monitor.check(path, unavailable, failed)
    assert not path.exists()
    sent = []
    monitor.check(path, unavailable, lambda *args: sent.append(args))
    assert "private details" not in str(sent)
    assert "needs attention" in sent[0][0]


def test_dry_run_never_publishes_or_writes(tmp_path):
    path = tmp_path / "state.json"
    sent = []
    monitor.check(path, lambda: report("attention"), lambda *args: sent.append(args), dry_run=True)
    assert not sent and not path.exists()


@pytest.mark.parametrize(
    "saved", ["broken", "[]", '{"notified_at":"bad"}', '{"notified_at":"2026-01-01T00:00:00"}']
)
def test_malformed_state_is_repaired(tmp_path, saved):
    path = tmp_path / "state.json"
    path.write_text(saved)
    sent = []
    result = monitor.check(path, lambda: report("attention"), lambda *args: sent.append(args))
    assert result["status"] == "attention" and len(sent) == 1
    assert "notified_at" in path.read_text()


def test_transient_preparation_lock_is_retried(monkeypatch):
    import json
    from types import SimpleNamespace

    results = iter(
        [
            SimpleNamespace(returncode=1, stdout=""),
            SimpleNamespace(returncode=0, stdout=json.dumps(report())),
        ]
    )
    waits = []
    monkeypatch.setattr(monitor.subprocess, "run", lambda *args, **kwargs: next(results))
    monkeypatch.setattr(monitor.time, "sleep", waits.append)
    assert monitor.fetch()["status"] == "ready"
    assert waits == [10]
