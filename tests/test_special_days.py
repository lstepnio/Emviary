import json

import pytest
from PIL import Image
from test_owner import sign_in

from emviary import render
from emviary.settings import FramePolicy, SpecialDay


def day(**changes):
    return SpecialDay(
        id="birthday",
        date="2000-10-08",
        label="Happy Birthday!",
        message="A little birdsong for your special day.",
        theme="birthday",
        **changes,
    ).model_dump()


def test_calendar_recurrence_priority_and_leap_day():
    birthday = day()
    leap = SpecialDay(id="leap", date="2024-02-29", label="Leap day").model_dump()
    assert render.special_day_for({"special_days": [birthday]}, "2026-10-08") == birthday
    assert render.special_day_for({"special_days": [birthday]}, "2026-10-09") is None
    assert (
        render.special_day_for({"special_days": [{**birthday, "annual": False}]}, "2026-10-08")
        is None
    )
    assert (
        render.special_day_for({"special_days": [{**birthday, "enabled": False}]}, "2026-10-08")
        is None
    )
    assert (
        render.special_day_for(
            {"special_days": [birthday, {**birthday, "id": "second"}]}, "2026-10-08"
        )
        == birthday
    )
    assert render.special_day_for({"special_days": [leap]}, "2027-02-28") is None
    assert render.special_day_for({"special_days": [leap]}, "2028-02-29") == leap
    with pytest.raises(ValueError):
        SpecialDay(id="invalid", date="2026-02-29", label="Invalid")
    with pytest.raises(ValueError):
        FramePolicy(max_birds=4)
    assert FramePolicy().max_birds == 3


def test_special_day_overrides_layout_without_changing_schedule(service, frame):
    selected = next(a for a in service.settings.artworks if a["id"] == "habird-bubo-virginianus")
    policy = service.settings.config.frame_defaults.model_dump()
    policy["special_days"] = [day(artwork_id=selected["id"])]
    service.store.set_policy(frame[0], FramePolicy.model_validate(policy))
    result = service.prepare(frame[0], "2026-10-08", offline=True)
    manifest = json.loads(result["manifest"])
    assert manifest["special_day"]["label"] == "Happy Birthday!"
    assert manifest["artworks"] == [selected]
    assert manifest["layout"]["bird_count"] == 1
    assert manifest["policy"]["wake_local_time"] == "03:15"
    assert service.prepare(frame[0], "2026-10-08", offline=True)["body_hash"] == result["body_hash"]
    preview = service.preview_special_day(frame[0], "birthday")
    assert preview[:2] == b"\xff\xd8"
    assert service.store.active_image(service.store.frame(frame[0]))["id"] == result["id"]
    ordinary = service.prepare(frame[0], "2026-10-09", offline=True)
    assert json.loads(ordinary["manifest"])["special_day"] is None


def test_owner_special_day_create_edit_delete_and_validation(service, frame, tmp_path, monkeypatch):
    client, csrf = sign_in(service, tmp_path, monkeypatch)
    page = client.get("/manage").text
    assert 'href="http://photoframe.local"' in page
    assert '<option value="3" selected>3</option>' in client.get("/manage/appearance").text
    url = "/manage/frames/test-frame/special-days"
    data = {
        "csrf": csrf,
        "date": "2026-10-08",
        "label": "Happy Birthday!",
        "message": "With love",
        "annual": "on",
        "enabled": "on",
        "theme": "birthday",
        "artwork_id": "habird-bubo-virginianus",
    }
    assert client.post(url, data={**data, "csrf": "wrong"}).status_code == 403
    assert client.post(url, data={**data, "date": "2026-02-30"}).status_code == 400
    assert client.post(url, data={**data, "artwork_id": "inky-common-raven"}).status_code == 400
    assert client.post(url, data={**data, "artwork_id": "habird-spinus-tristis"}).status_code == 400
    assert client.post(url, data=data, follow_redirects=False).status_code == 303
    events = json.loads(service.store.frame(frame[0])["policy"])["special_days"]
    assert len(events) == 1 and events[0]["annual"]
    identifier = events[0]["id"]
    service.prepare(frame[0], "2026-10-08", offline=True)
    before = service.store.active_image(service.store.frame(frame[0]))["id"]
    response = client.get(url + "/" + identifier + "/preview")
    assert response.status_code == 200 and response.headers["content-type"] == "image/jpeg"
    assert service.store.active_image(service.store.frame(frame[0]))["id"] == before
    assert (
        client.post(
            url,
            data={**data, "id": identifier, "message": "Another wonderful year"},
            follow_redirects=False,
        ).status_code
        == 303
    )
    events = json.loads(service.store.frame(frame[0])["policy"])["special_days"]
    assert len(events) == 1 and events[0]["message"] == "Another wonderful year"
    assert (
        client.post(
            url + "/" + identifier + "/delete", data={"csrf": csrf}, follow_redirects=False
        ).status_code
        == 303
    )
    assert json.loads(service.store.frame(frame[0])["policy"])["special_days"] == []


def test_long_labels_and_greetings_fit_without_touching_bird_pixels(service, tmp_path):
    works = [
        next(a for a in service.settings.artworks if a["scientific_name"] == name)
        for name in ("Sitta carolinensis", "Poecile atricapillus", "Agelaius phoeniceus")
    ]
    policy = service.settings.config.frame_defaults.model_dump()
    plan = {"local_date": "2026-10-08", "inputs": {}, "policy": policy, "artworks": works}
    path = tmp_path / "three.png"
    render.compose(service.settings.art_dir, works[0], plan, path)
    with Image.open(path) as image:
        assert image.size == (800, 480)
    event = {**day(), "label": "W" * 40, "message": "W" * 80}
    plan.update(artworks=[works[0]], special_day=event)
    render.compose(service.settings.art_dir, works[0], plan, path)
    with Image.open(path) as image:
        assert json.loads(image.info["eink_neutral_bands"])[1][0] == 328
