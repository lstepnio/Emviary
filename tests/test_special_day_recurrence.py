from datetime import date

from test_owner import sign_in

from emviary import render
from emviary.event_art import event_presets, import_presets, special_day_conflicts
from emviary.settings import FramePolicy, SpecialDay


def test_movable_presets_follow_calendar_across_years_without_duplicate_imports():
    entries = event_presets("holidays", 2026)
    expected = {
        "Thanksgiving": ("2027-11-25", "2028-11-23"),
        "Mother's Day": ("2027-05-09", "2028-05-14"),
        "Memorial Day": ("2027-05-31", "2028-05-29"),
        "Labor Day": ("2027-09-06", "2028-09-04"),
    }
    for label, dates in expected.items():
        event = next(e for e in entries if e["label"] == label)
        event["enabled"] = True
        for when in dates:
            assert render.special_day_for({"special_days": [event]}, when) == event
        assert render.special_day_for({"special_days": [event]}, "2027" + event["date"][4:]) is None
    assert import_presets(entries, "holidays", 2027) == entries


def test_legacy_migration_preserves_every_existing_field_and_custom_dates():
    original = next(e for e in event_presets("holidays", 2026) if e["label"] == "Thanksgiving")
    original.pop("recurrence")
    original.pop("priority")
    original.update(message="Our greeting", artwork_id="custom-art", enabled=True)
    migrated = SpecialDay.model_validate(original).model_dump()
    assert {k: migrated[k] for k in original} == original
    assert migrated["recurrence"] == dict(kind="nth_weekday", month=11, weekday=3, ordinal=4)
    for customized in (
        {**original, "date": "2026-11-27"},
        {**original, "label": "Our Thanksgiving"},
        {**original, "id": "custom-thanksgiving"},
        {**original, "annual": True},
        {**original, "recurrence": None},
    ):
        assert SpecialDay.model_validate(customized).recurrence is None
    policy = FramePolicy(special_days=[original])
    assert FramePolicy.model_validate_json(policy.model_dump_json()) == policy


def test_overlaps_warn_and_runtime_uses_same_priority_and_saved_order():
    entries = [
        SpecialDay(
            id=identifier, date="2026-11-26", label=identifier, priority=priority
        ).model_dump()
        for identifier, priority in (("first", 0), ("second", 10), ("third", 10))
    ]
    conflicts = special_day_conflicts(entries, date(2026, 10, 12))
    assert len(conflicts) == 5
    assert [e["id"] for e in conflicts[0][1]] == ["second", "third", "first"]
    assert render.special_day_for({"special_days": entries}, "2026-11-26")["id"] == "second"
    entries[1]["enabled"] = False
    assert render.special_day_for({"special_days": entries}, "2026-11-26")["id"] == "third"
    assert "second" not in [e["id"] for e in special_day_conflicts(entries, date(2026, 1, 1))[0][1]]


def test_owner_saves_recurring_rule_and_displays_overlap_winner(
    service, frame, tmp_path, monkeypatch
):
    client, csrf = sign_in(service, tmp_path, monkeypatch)
    url = "/manage/frames/test-frame/special-days"
    base = dict(
        csrf=csrf,
        date="2026-11-26",
        label="Thanksgiving",
        theme="celebration",
        enabled="on",
        date_rule="nth_weekday",
        rule_month="11",
        rule_weekday="3",
        rule_ordinal="4",
        priority="20",
    )
    assert client.post(url, data=base, follow_redirects=False).status_code == 303
    policy = FramePolicy.model_validate_json(service.store.frame(frame[0])["policy"])
    event = policy.special_days[0]
    assert event.recurrence.ordinal == 4 and event.priority == 20
    assert event.date == "2026-11-26" and not event.annual
    assert render.special_day_for(policy.model_dump(), "2027-11-25")["label"] == "Thanksgiving"
    policy.special_days.append(SpecialDay(id="other", date="2026-11-26", label="Other"))
    service.store.set_policy(frame[0], policy)
    page = client.get("/manage/events").text
    assert "Overlapping special days" in page
    assert "Thanksgiving will display instead of Other" in page
    assert 'name="date_rule"' in page and 'name="priority"' in page
    for invalid in (
        dict(rule_month="13"),
        dict(rule_weekday="7"),
        dict(rule_ordinal="5"),
        dict(priority="101"),
    ):
        assert client.post(url, data={**base, **invalid}).status_code == 400


def test_dated_preset_copies_preserved_but_identical_recurrences_do_not_conflict():
    entries = [
        next(e for e in event_presets("holidays", year) if e["label"] == "Mother's Day")
        for year in (2026, 2027)
    ]
    for entry in entries:
        entry.update(enabled=True, artwork_id="same-art")
    policy = FramePolicy(special_days=entries).model_dump()
    assert len(policy["special_days"]) == 2
    assert not special_day_conflicts(policy["special_days"], date(2026, 1, 1))
    assert render.special_day_for(policy, "2027-05-09")["id"].endswith("2027")
    assert render.special_day_for(policy, "2028-05-14")["id"].endswith("2027")
    policy["special_days"][1]["message"] = "A custom greeting"
    assert len(special_day_conflicts(policy["special_days"], date(2026, 1, 1))) == 5
    assert render.special_day_for(policy, "2027-05-09")["id"].endswith("2026")
