from datetime import date

from test_owner import sign_in

from emviary import render
from emviary.settings import FramePolicy, Location
from emviary.wildlife import eligible_wildlife, wildlife_dates


def test_twice_monthly_cadence_is_stable_spaced_and_avoids_special_days():
    policy = FramePolicy(wildlife_per_month=2).model_dump()
    for month in range(1, 13):
        dates = wildlife_dates("gift", 2028, month, policy)
        assert len(dates) == 2 and int(dates[0][-2:]) <= 14 < int(dates[1][-2:])
        assert (date.fromisoformat(dates[1]) - date.fromisoformat(dates[0])).days >= 8
        assert wildlife_dates("gift", 2028, month, policy) == dates
        blocked = {**policy, "special_days": [dict(date=dates[0], annual=True, enabled=True)]}
        assert dates[0] not in wildlife_dates("gift", 2028, month, blocked)
    assert not wildlife_dates("gift", 2028, 1, {**policy, "wildlife_per_month": 0})


def test_region_and_season_filters_match_colorado_without_using_bird_reports(service):
    site = service.settings.config.site("denver-gift")
    winter = eligible_wildlife(service.settings.artworks, site, "2026-01-08")
    summer = eligible_wildlife(service.settings.artworks, site, "2026-07-08")
    assert len(winter) == 10 and len(summer) == 12
    assert all("US-CO" in a["regions"] for a in summer)
    elsewhere = site.model_copy(
        update={"bird_area": "local", "weather_location": Location(latitude=47, longitude=-122)}
    )
    from emviary.settings import Site

    elsewhere = Site.model_validate(elsewhere.model_dump())
    assert not eligible_wildlife(service.settings.artworks, elsewhere, "2026-07-08")


def test_wildlife_plan_is_solo_birds_remain_default_and_exclusion_falls_back(service, frame):
    policy = FramePolicy(wildlife_per_month=2)
    service.store.set_policy(frame[0], policy)
    when = wildlife_dates(frame[0], 2026, 7, policy.model_dump())[0]
    plan = service._new_plan(service.store.frame(frame[0]), when, 0, "test", True)
    assert plan["content_category"] == "wildlife" and len(plan["artworks"]) == 1
    assert plan["layout"]["bird_count"] == 0 and plan["artwork"]["depicted_animals"] == 1
    assert not plan["special_day"]
    ordinary = next(
        date(2026, 7, n).isoformat()
        for n in range(1, 32)
        if date(2026, 7, n).isoformat()
        not in wildlife_dates(frame[0], 2026, 7, policy.model_dump())
    )
    birds = service._new_plan(service.store.frame(frame[0]), ordinary, 0, "test", True)
    assert birds["content_category"] == "birds"
    assert all(a.get("category", "bird") == "bird" for a in birds["artworks"])
    for art in service.settings.artworks:
        if art.get("category") == "wildlife":
            with service.store.connect() as db:
                db.execute("INSERT INTO excluded_artworks(id) VALUES(?)", (art["id"],))
    fallback = service._new_plan(service.store.frame(frame[0]), when, 0, "test", True)
    assert fallback["content_category"] == "birds"


def test_every_wildlife_master_composes_without_cropping_or_fake_bird_counts(service, tmp_path):
    from contextlib import closing

    from PIL import Image

    policy = FramePolicy(show_location_name=True).model_dump()
    animals = [a for a in service.settings.artworks if a.get("category") == "wildlife"]
    assert len(animals) == 12
    for art in animals:
        with closing(Image.open(service.settings.art_dir / art["asset"])) as image:
            assert image.mode == "RGBA" and image.getchannel("A").getextrema() == (0, 255)
        plan = dict(
            local_date="2026-07-12",
            seed="wildlife",
            policy=policy,
            artworks=[art],
            special_day=None,
            location_label="COLORADO",
            inputs={},
            layout=dict(name="solo", bird_count=0),
        )
        output = tmp_path / (art["id"] + ".png")
        render.compose(service.settings.art_dir, art, plan, output)
        with closing(Image.open(output)) as image:
            assert image.size == (800, 480)


def test_wildlife_library_search_and_subject_filter(service, frame, tmp_path, monkeypatch):
    client, _ = sign_in(service, tmp_path, monkeypatch)
    page = client.get("/manage/artwork?frame=" + frame[0] + "&category=wildlife")
    assert page.status_code == 200 and "12 artworks" in page.text
    assert "Colorado · Mammal" in page.text and "Mule Deer" in page.text
    assert "Black-capped Chickadee" not in page.text
    page = client.get("/manage/artwork?q=riparian&category=wildlife")
    assert "Raccoon" in page.text and "Beaver" in page.text
    assert "Pronghorn" not in page.text


def test_wildlife_avoids_recent_species_then_uses_the_oldest(service):
    from emviary.wildlife import choose_wildlife

    animals = [a for a in service.settings.artworks if a.get("category") == "wildlife"]
    history = [dict(artwork=a, artworks=[a]) for a in animals]
    assert choose_wildlife(animals, "0" * 64, history) == animals[-1]
    assert choose_wildlife(animals, "0" * 64, history[:-1]) == animals[-1]
