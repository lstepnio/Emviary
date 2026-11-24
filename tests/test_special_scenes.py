import pytest
from test_owner import sign_in

from emviary.settings import SpecialDay
from emviary.special_scenes import scene_art, validate_words


@pytest.mark.parametrize("direction", ["season", "memory"])
@pytest.mark.parametrize("composition", ["scene", "dedication"])
def test_scene_draft_is_read_only(service, frame, tmp_path, monkeypatch, direction, composition):
    client, csrf = sign_in(service, tmp_path, monkeypatch)
    identifier = frame[0]
    before = service.store.frame(identifier)
    art = scene_art(direction)
    assert art["approved"] and art["event_only"]
    response = client.post(
        f"/manage/frames/{identifier}/special-day-proof",
        data={
            "csrf": csrf,
            "date": "2026-12-21",
            "label": "A day together",
            "direction": direction,
            "composition": composition,
            "heading": "Questionable directions."
            if direction == "memory"
            else "More daylight. Finally.",
            "message": "Excellent company." if direction == "memory" else "Still better with you.",
        },
    )
    assert response.status_code == 200, response.text[:300] if response.status_code != 200 else ""
    proof = client.get(response.json()["image_url"])
    assert proof.status_code == 200
    assert proof.headers["content-type"] == "image/jpeg"
    assert (
        client.get(response.json()["image_url"].replace(identifier, "other-frame")).status_code
        == 404
    )
    assert service.store.frame(identifier) == before
    assert not service.store.active_image(before)


def test_existing_art_retained_and_words_fit(service, frame, tmp_path, monkeypatch):
    client, csrf = sign_in(service, tmp_path, monkeypatch)
    page = client.get("/manage/events").text
    assert "Seasonal nature" in page and "A personal memory" in page
    assert "Existing art & original layout" in page
    assert "Preview picture" in page
    assert SpecialDay(id="old", date="2026-12-21", label="Original").direction == "existing"
    with pytest.raises(ValueError, match="too wide"):
        validate_words(
            service.settings.art_dir,
            dict(
                direction="memory",
                composition="dedication",
                label="Original",
                heading="W" * 40,
                message="",
            ),
        )
    response = client.post(f"/manage/frames/{frame[0]}/special-day-proof", data={"csrf": "invalid"})
    assert response.status_code in (400, 403)


def test_memory_notes_never_enter_delivery_plan(service, frame):
    from emviary.settings import FramePolicy

    day = dict(
        id="memory",
        date="2026-12-21",
        label="Together",
        direction="memory",
        heading="Questionable directions.",
        message="Excellent company.",
        memory_note="PRIVATE-MEMORY-NOTE",
    )
    service.store.set_policy(frame[0], FramePolicy(special_days=[day]))
    current = service.store.frame(frame[0])
    plan = service._new_plan(current, "2026-12-21", 0, "test", True, "memory")
    import json

    assert "PRIVATE-MEMORY-NOTE" not in json.dumps(plan)
    assert "PRIVATE-MEMORY-NOTE" in current["policy"]


def test_scene_text_matches_review_layout_when_system_supports_shaping(service, monkeypatch):
    from PIL import ImageFont, features

    from emviary import render
    from emviary.special_scenes import scene_font

    base = render._font(service.settings.art_dir, 30)
    expected = ImageFont.truetype(base.path, base.size, layout_engine=ImageFont.Layout.BASIC)
    system = base.font_variant(
        layout_engine=ImageFont.Layout.RAQM if features.check("raqm") else ImageFont.Layout.BASIC
    )
    monkeypatch.setattr(render, "_font", lambda art_dir, size: system)
    actual = scene_font(service.settings.art_dir, 30, serif=True)
    phrase = "New year. Same us."
    assert actual.getlength(phrase) == expected.getlength(phrase)
    assert bytes(actual.getmask(phrase)) == bytes(expected.getmask(phrase))
