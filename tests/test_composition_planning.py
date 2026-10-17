import json
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest
from test_freshness import install_weather
from test_owner import sign_in
from test_public_ui import public_client

from emviary.backup_validation import verify_backup
from emviary.compositions import composition_key
from emviary.service import Service
from emviary.settings import FramePolicy


def reservation(service, frame, day):
    return service.store.daily_composition(frame[0], day)


def test_advance_composition_is_persistent_neutral_and_not_deliverable(service, frame, monkeypatch):
    clock, calls = install_weather(service, monkeypatch)
    clock[0] = datetime(2026, 10, 8, 16, tzinfo=UTC)  # After today's wake.
    service.prepare_due()
    planned = reservation(service, frame, "2026-10-09")
    plan = json.loads(planned["plan"])
    assert planned["preview_path"] and "open_meteo" not in plan["inputs"]
    assert plan["local_date"] == "2026-10-09"
    assert not ({"wifi_networks", "wifi_forget_ssids"} & plan["policy"].keys())
    with service.store.connect() as db:
        assert (
            db.execute("SELECT count(*) FROM images WHERE local_date='2026-10-09'").fetchone()[0]
            == 0
        )
    daily = service.store.slot_image(frame[0], "scheduled")
    before = (daily["id"], service.store.bird_counts(), len(calls))
    restarted = Service(service.settings, service.providers, service.converter, clock=service.clock)
    upcoming = restarted.next_daily_refresh(restarted.store.frame(frame[0]))
    assert upcoming["status"] == "planned" and upcoming["image"] is None
    assert upcoming["preview"]["preview_path"] == planned["preview_path"]
    restarted.prepare_due()
    assert reservation(service, frame, "2026-10-09") == planned
    assert (
        service.store.slot_image(frame[0], "scheduled")["id"],
        service.store.bird_counts(),
        len(calls),
    ) == before


def test_final_weather_refresh_preserves_reserved_composition_exactly(
    service, frame, monkeypatch, tmp_path
):
    clock, _ = install_weather(service, monkeypatch)
    clock[0] = datetime(2026, 10, 8, 16, tzinfo=UTC)
    service.prepare_due()
    planned = json.loads(reservation(service, frame, "2026-10-09")["plan"])
    clock[0] = datetime(2026, 10, 9, 8, 30, tzinfo=UTC)
    service.prepare_due()
    daily = service.store.slot_image(frame[0], "scheduled")
    final = json.loads(daily["manifest"])
    assert composition_key(final) == composition_key(planned)
    assert final["artworks"] == planned["artworks"] and final["layout"] == planned["layout"]
    assert final["inputs"]["open_meteo"]["fetched_at"] == clock[0].isoformat()
    # The full rendered composition below the weather strip is identical.
    from PIL import Image, ImageChops

    from emviary import render

    neutral = tmp_path / "planned-master.png"
    render.compose(
        service.settings.art_dir, planned["artwork"], planned, neutral, service.event_art.root
    )
    master = service.cache_path(str(Path(daily["path"]).with_suffix("")) + "-master.png")
    with Image.open(neutral) as a, Image.open(master) as b:
        assert (
            ImageChops.difference(a.convert("RGB"), b.convert("RGB"))
            .crop((0, 48, 800, 480))
            .getbbox()
            is None
        )
    assert service.next_daily_refresh(service.store.frame(frame[0]))["status"] == "ready"


def test_settings_change_invalidates_plan_and_both_preview_routes(
    service, frame, monkeypatch, tmp_path
):
    clock, _ = install_weather(service, monkeypatch)
    clock[0] = datetime(2026, 10, 8, 16, tzinfo=UTC)
    service.prepare_due()
    old = reservation(service, frame, "2026-10-09")
    client, _ = sign_in(service, tmp_path, monkeypatch)
    assert client.get("/manage/frames/test-frame/prepared/scheduled").status_code == 200
    policy = FramePolicy.model_validate_json(service.store.frame(frame[0])["policy"])
    policy.max_birds = 1
    service.store.set_policy(frame[0], policy)
    assert service.next_daily_refresh(service.store.frame(frame[0]))["preview"] is None
    assert client.get("/manage/frames/test-frame/prepared/scheduled").status_code == 404
    service.prepare_due()
    new = reservation(service, frame, "2026-10-09")
    assert new["configuration_hash"] != old["configuration_hash"]
    assert json.loads(new["plan"])["layout"]["bird_count"] == 1


def test_public_and_owner_show_the_same_planned_composition_without_rendering_on_get(
    service, frame, monkeypatch, tmp_path
):
    clock, _ = install_weather(service, monkeypatch)
    clock[0] = datetime(2026, 10, 8, 16, tzinfo=UTC)
    public = public_client(service, frame)
    service.prepare_due()
    owner, _ = sign_in(service, tmp_path, monkeypatch)
    before = service.store.bird_counts()
    monkeypatch.setattr(service, "converter", lambda *args: pytest.fail("Render on GET"))
    monkeypatch.setattr(
        service.providers, "inputs", lambda *args, **kwargs: pytest.fail("Provider on GET")
    )
    response = public.get("/")
    assert "Coming up" in response.text and "/display/next-daily.jpg" in response.text
    assert "Oct 09, 03:15 AM" in response.text
    assert "Composition planned" in owner.get("/manage").text
    a = owner.get("/manage/frames/test-frame/prepared/scheduled")
    b = public.get("/display/next-daily.jpg")
    assert a.status_code == b.status_code == 200 and a.content == b.content
    assert b.headers["cache-control"] == "no-store"
    assert service.store.bird_counts() == before
    config = service.settings.config.model_dump()
    config["public_frame_id"] = None
    service.save_configuration(config)
    assert public.get("/display/next-daily.jpg").status_code == 404


def test_preview_failure_is_bounded_and_does_not_prevent_final_daily_image(
    service, frame, monkeypatch
):
    clock, _ = install_weather(service, monkeypatch)
    converter = service.converter

    def fail_preview(source, *args):
        if source.name == "composition.png":
            raise TimeoutError()
        return converter(source, *args)

    monkeypatch.setattr(service, "converter", fail_preview)
    for minute in (0, 1, 15, 16, 30, 31, 45):
        service.prepare_due(clock[0] + timedelta(minutes=minute))
    planned = reservation(service, frame, "2026-10-08")
    assert planned["attempts"] == 3 and planned["error"] == "TimeoutError"
    assert planned["plan"] and planned["preview_path"] is None
    clock[0] = datetime(2026, 10, 8, 8, 30, tzinfo=UTC)
    service.prepare_due()
    assert service.store.slot_image(frame[0], "scheduled") is not None


def test_planned_preview_survives_backup_restore(service, frame, monkeypatch, tmp_path):
    clock, _ = install_weather(service, monkeypatch)
    clock[0] = datetime(2026, 10, 8, 16, tzinfo=UTC)
    service.prepare_due()
    plan = reservation(service, frame, "2026-10-09")
    backup = Path(service.backup(tmp_path / "backup"))
    assert (backup / "active-cache" / Path(plan["preview_path"]).relative_to("cache")).is_file()
    assert verify_backup(backup)["restore_rehearsal"] == "passed"


def test_failed_backup_does_not_starve_navigation_refill(service, frame, monkeypatch):
    install_weather(service, monkeypatch)
    first = service.prepare(frame[0])
    service.store.request_refill(frame[0], first["id"])
    monkeypatch.setattr(service, "_backup", lambda *args: (_ for _ in ()).throw(PermissionError()))
    service.prepare_due(datetime(2026, 10, 8, 16, tzinfo=UTC))
    assert not service.store.pending_refills()


def test_history_and_buttons_group_weather_revisions_and_exclude_current_composition(
    service, frame, monkeypatch
):
    clock, _ = install_weather(service, monkeypatch)
    first = service.prepare(frame[0])
    clock[0] += timedelta(minutes=5)
    first_weather = service._prepare(frame[0], None, True, False, reuse_image=first)
    second = service.prepare(frame[0], force=True)
    assert composition_key(first) != composition_key(second)
    clock[0] += timedelta(minutes=5)
    current = service._prepare(frame[0], None, True, False, reuse_image=second)
    assert composition_key(first) == composition_key(first_weather)
    assert composition_key(second) == composition_key(current)
    past = service.store.past_compositions(frame[0], current["id"], 10)
    assert [image["id"] for image in past] == [first_weather["id"]]
    assert [
        image["id"] for image in service.store.past_compositions(frame[0], current["id"], 1)
    ] == [first_weather["id"]]
    assert (
        service.store.navigation_image(
            service.store.frame(frame[0]), "previous", current["body_hash"]
        )["id"]
        == first_weather["id"]
    )
    assert (
        service.store.navigation_image(service.store.frame(frame[0]), "next", first["body_hash"])[
            "id"
        ]
        == second["id"]
    )
    with service.store.connect() as db:
        db.execute("UPDATE images SET hidden=1 WHERE id=?", (first_weather["id"],))
    assert [
        image["id"] for image in service.store.past_compositions(frame[0], current["id"], 10)
    ] == [first["id"]]


def test_same_birds_with_different_layout_or_greeting_remain_distinct(service, frame):
    plan = json.loads(service.prepare(frame[0])["manifest"])
    original = composition_key(plan)
    other_layout = {**plan, "layout": {**plan["layout"], "name": "different"}}
    assert composition_key(other_layout) != original
    greeting = {
        **plan,
        "special_day": {"label": "Happy Birthday", "message": "Hi", "theme": "celebration"},
    }
    assert composition_key(greeting) != original
    old_weather = {
        **plan,
        "revision": 99,
        "inputs": {"open_meteo": {"values": {"temperature_2m_max": 99}}},
    }
    assert composition_key(old_weather) == original


def test_special_day_plan_keeps_its_art_and_greeting_when_weather_is_added(
    service, frame, monkeypatch
):
    clock, _ = install_weather(service, monkeypatch)
    artwork = next(
        a
        for a in service.settings.artworks
        if a.get("approved")
        and a.get("depicted_birds", 1) == 1
        and 10 in a["months"]
        and a.get("category", "bird") == "bird"
    )
    policy = FramePolicy(
        special_days=[
            {
                "id": "birthday",
                "date": "2026-10-09",
                "label": "Happy Birthday",
                "message": "Have a lovely day",
                "artwork_id": artwork["id"],
                "theme": "celebration",
            }
        ]
    )
    service.store.set_policy(frame[0], policy)
    clock[0] = datetime(2026, 10, 8, 16, tzinfo=UTC)
    service.prepare_due()
    plan = json.loads(reservation(service, frame, "2026-10-09")["plan"])
    assert plan["content_category"] == "special_day"
    assert plan["artwork"]["id"] == artwork["id"]
    clock[0] = datetime(2026, 10, 9, 8, 30, tzinfo=UTC)
    service.prepare_due()
    final = json.loads(service.store.slot_image(frame[0], "scheduled")["manifest"])
    assert final["special_day"] == plan["special_day"]
    assert final["layout"] == plan["layout"]
    assert composition_key(final) == composition_key(plan)


def test_changed_wake_or_freshness_policy_changes_schedule_cycle(service, frame):
    from datetime import date

    original = service.daily_schedule(service.store.frame(frame[0]), date(2026, 10, 9))
    policy = FramePolicy(wake_local_time="04:15", firmware_rotate_cron=["15 4 *"])
    service.store.set_policy(frame[0], policy)
    updated = service.daily_schedule(service.store.frame(frame[0]), date(2026, 10, 9))
    assert updated["cycle"] != original["cycle"]
    policy.weather_max_age_minutes = 30
    service.store.set_policy(frame[0], policy)
    assert (
        service.daily_schedule(service.store.frame(frame[0]), date(2026, 10, 9))["cycle"]
        != updated["cycle"]
    )


def test_upgrade_preserves_completed_legacy_daily_slot(service, frame, monkeypatch):
    clock, _ = install_weather(service, monkeypatch)
    clock[0] = datetime(2026, 10, 8, 8, 30, tzinfo=UTC)
    service.prepare_due()
    image = service.store.slot_image(frame[0], "scheduled")
    row = service.store.frame(frame[0])
    site = service.settings.config.site(row["site_id"])
    legacy_cycle = "2026-10-08:" + site.prepare_local_time + ":" + service.configuration_hash(row)
    with service.store.connect() as db:
        db.execute(
            "UPDATE prepared_slots SET cycle=? WHERE frame_id=? AND purpose='scheduled'",
            (legacy_cycle, frame[0]),
        )
    clock[0] = datetime(2026, 10, 8, 16, tzinfo=UTC)
    service.prepare_due()
    assert service.store.slot_image(frame[0], "scheduled")["id"] == image["id"]
