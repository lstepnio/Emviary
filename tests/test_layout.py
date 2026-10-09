import gzip

from PIL import Image

from emviary import render


def test_panel_limits_and_species_rules(service, tmp_path):
    policy = service.settings.config.frame_defaults.model_dump()
    outcomes = set()
    for number in range(20):
        selected = render.choose_artworks(
            service.settings.artworks, "2026-10-08", {}, [], str(number), policy
        )
        outcomes.add(len(selected))
        assert len(selected) <= 3
        assert len({a["scientific_name"] for a in selected}) == len(selected)
        plan = {
            "local_date": "2026-10-08",
            "seed": str(number),
            "inputs": {},
            "policy": policy,
            "artworks": selected,
        }
        path = tmp_path / f"layout-{number}.png"
        render.compose(service.settings.art_dir, selected[0], plan, path)
        with Image.open(path) as image:
            assert image.size == (800, 480)
    assert outcomes == {1, 2, 3}
    policy["max_birds"] = 1
    assert (
        len(render.choose_artworks(service.settings.artworks, "2026-10-08", {}, [], "2", policy))
        == 1
    )


def test_white_paper_uses_white_ink_without_changing_art(tmp_path):
    source = tmp_path / "source.png"
    target = tmp_path / "packed.epdgz"
    image = Image.new("RGB", (800, 480), "white")
    image.putpixel((0, 0), (200, 0, 0))
    image.putpixel((1, 0), (255, 254, 255))
    image.save(source)
    original = bytes([0x35]) * 192000
    target.write_bytes(gzip.compress(original))
    render.preserve_paper_white(source, target)
    corrected = gzip.decompress(target.read_bytes())
    assert corrected[:1] == original[:1]
    assert corrected[1:] == bytes([0x11]) * 191999
    render.validate_epdgz(target)


def test_neutral_graphics_preserve_bird_pixels(tmp_path):
    import gzip

    from PIL import Image

    from emviary.render import preserve_neutral_graphics

    source = tmp_path / "source.png"
    target = tmp_path / "panel.epdgz"
    image = Image.new("RGB", (800, 480), "white")
    for point in ((60, 39), (400, 415), (400, 451), (400, 200)):
        image.putpixel(point, (51, 51, 51))
    image.putpixel((65, 39), (135, 19, 0))
    image.save(source)
    target.write_bytes(gzip.compress(bytes([0x33]) * 192000))
    preserve_neutral_graphics(source, target)
    packed = gzip.decompress(target.read_bytes())

    def ink(x, y):
        index = y * 800 + x
        return (packed[index // 2] >> (0 if index % 2 else 4)) & 15

    assert ink(60, 39) == 0
    assert ink(400, 451) == 0
    assert ink(400, 415) == 3  # Reclaimed art pixels retain their color conversion.
    assert ink(70, 39) == 1
    assert ink(65, 39) == 3  # Colored content is not recolored.
    assert ink(400, 200) == 3  # Bird-cell pixels keep the color conversion.


def test_composition_has_safe_nonoverlapping_art_and_caption_regions():
    layouts = {
        1: ["solo", "solo-left", "solo-right", "plate", "occasion"],
        2: ["pair", "lead-left-pair", "lead-right-pair"],
        3: ["trio", "lead-left-trio", "lead-right-trio", "center-lead-trio"],
    }
    for count, names in layouts.items():
        for name in names:
            cells, captions = render.composition_cells(name, count)
            assert len(cells) == len(captions) == count
            for left, top, right, bottom in cells:
                assert 24 <= left < right <= 776
                assert 48 <= top < bottom <= 412
            for index, (left, top, right, bottom) in enumerate(cells):
                for other_left, other_top, other_right, other_bottom in cells[index + 1 :]:
                    assert (
                        right <= other_left
                        or other_right <= left
                        or bottom <= other_top
                        or other_bottom <= top
                    )
            for center, width in captions:
                assert 20 <= center - width / 2 < center + width / 2 <= 780


def test_layout_restores_centered_columns_and_preserves_wings(service):
    art = next(a for a in service.settings.artworks if a.get("facing") == "left")
    for seed in map(str, range(30)):
        assert render.choose_layout([art], seed) == "solo"
        assert render.choose_layout([art, art], seed) == "pair"
        assert render.choose_layout([art, art, art], seed) == "trio"
    wide = next(
        a
        for a in service.settings.artworks
        if a.get("kind", "cutout") == "cutout"
        and render.artwork_aspect(service.settings.art_dir, a) > 1.6
    )
    assert render.choose_layout([wide], "wide", art_dir=service.settings.art_dir) == "solo"
    history = [{"layout": {"name": "pair"}}]
    assert render.choose_layout([art, art], "fresh", history) == "pair"
    assert render.composition_cells("lead-left-trio", 3) == render.composition_cells("trio", 3)


def test_detail_capacity_overrides_three_bird_default(service):
    birds = [a for a in service.settings.artworks if a["approved"] and a.get("kind") == "cutout"]
    constrained = [{**a, "composition_max_birds": 2} for a in birds]
    policy = service.settings.config.frame_defaults.model_dump()
    for seed in map(str, range(30)):
        assert len(render.choose_artworks(constrained, "2026-10-08", {}, [], seed, policy)) <= 2


def test_seasonal_motifs_leave_a_white_gap_inside_the_border(service, tmp_path):
    art = next(a for a in service.settings.artworks if a["approved"] and a.get("kind") == "cutout")
    policy = service.settings.config.frame_defaults.model_dump()
    for month in (1, 4, 7, 10):
        source = tmp_path / f"margin-{month}.png"
        plan = {
            "local_date": f"2026-{month:02d}-08",
            "inputs": {},
            "policy": policy,
            "artworks": [art],
            "layout": {"name": "solo"},
        }
        render.compose(service.settings.art_dir, art, plan, source)
        with Image.open(source) as image:
            for y in range(270, 380):
                for x in (*range(9, 14), *range(786, 791)):
                    assert image.getpixel((x, y))[:3] == (255, 255, 255)


def test_location_name_header_omits_date_and_can_be_enabled(service, tmp_path, monkeypatch):
    from PIL import ImageChops

    policy = service.settings.config.frame_defaults.model_dump()
    assert policy["show_location_name"] is False
    # Existing saved policies receive the same default when loaded.
    from emviary.settings import FramePolicy

    assert FramePolicy.model_validate({"site_id": "denver-gift"}).show_location_name is False
    assert FramePolicy.model_validate({"show_location_date": True}).show_location_name is True
    artwork = next(
        a
        for a in service.settings.artworks
        if a["approved"] and a.get("kind", "cutout") == "cutout"
    )
    plan = dict(
        local_date="2026-10-08",
        location_label="COLORADO",
        seed="header",
        inputs={},
        policy=policy,
        artworks=[artwork],
    )
    from PIL import ImageDraw

    text_calls = []
    original_text = ImageDraw.ImageDraw.text

    def record_text(self, xy, text, *args, **kwargs):
        text_calls.append(text)
        return original_text(self, xy, text, *args, **kwargs)

    monkeypatch.setattr(ImageDraw.ImageDraw, "text", record_text)
    hidden = tmp_path / "hidden.png"
    visible = tmp_path / "visible.png"
    render.compose(service.settings.art_dir, artwork, plan, hidden)
    first_hash = render.profile_hash(policy, [])
    policy["show_location_name"] = True
    assert render.profile_hash(policy, []) != first_hash
    render.compose(service.settings.art_dir, artwork, plan, visible)
    assert "COLORADO" in text_calls
    assert not any("2026-10-08" in text for text in text_calls)
    with Image.open(hidden) as first, Image.open(visible) as second:
        assert len(first.crop((24, 16, 350, 45)).getcolors()) == 1
        changed = ImageChops.difference(first, second).getbbox()
        assert changed is not None
        assert changed[0] >= 24 and changed[1] >= 12
        assert changed[2] <= 350 and changed[3] <= 45


def test_frame_labels_use_only_common_names_and_leave_room_for_larger_art(
    service, tmp_path, monkeypatch
):
    from PIL import ImageDraw

    texts = []
    text_boxes = []
    original = ImageDraw.ImageDraw.text

    def record_text(self, xy, text, *args, **kwargs):
        texts.append(text)
        text_boxes.append(
            self.textbbox(xy, text, font=kwargs.get("font"), anchor=kwargs.get("anchor"))
        )
        return original(self, xy, text, *args, **kwargs)

    monkeypatch.setattr(ImageDraw.ImageDraw, "text", record_text)
    birds = [
        a
        for a in service.settings.artworks
        if a["approved"] and a.get("kind", "cutout") == "cutout"
    ][:3]
    policy = service.settings.config.frame_defaults.model_dump()
    for count in (1, 2, 3):
        selected = birds[:count]
        plan = dict(
            local_date="2026-10-08",
            seed="common-names",
            inputs={},
            policy=policy,
            artworks=selected,
        )
        texts.clear()
        text_boxes.clear()
        render.compose(service.settings.art_dir, selected[0], plan, tmp_path / f"names-{count}.png")
        assert all(420 < top < bottom < 471 for _, top, _, bottom in text_boxes)
        with Image.open(tmp_path / f"names-{count}.png") as image:
            assert image.getpixel((20, 420)) == (51, 51, 51)
        assert all(a["common_name"] in " ".join(texts) for a in selected)
        assert all(a["scientific_name"] not in " ".join(texts) for a in selected)
    # The art reaches lower without entering the common-name caption band.
    cells, _ = render.composition_cells("solo", 1)
    assert cells[0][3] > 400
    assert cells[0][3] < 428


def test_header_long_forecast_is_clear_and_does_not_overlap_location(
    service, tmp_path, monkeypatch
):
    from PIL import ImageDraw

    art = next(
        a
        for a in service.settings.artworks
        if a["approved"] and a.get("kind", "cutout") == "cutout"
    )
    policy = service.settings.config.frame_defaults.model_dump()
    policy["show_location_name"] = True
    header_boxes = []
    original = ImageDraw.ImageDraw.text

    def capture(self, xy, text, *args, **kwargs):
        if xy[1] == 25:
            header_boxes.append(
                self.textbbox(xy, text, font=kwargs["font"], anchor=kwargs.get("anchor"))
            )
        return original(self, xy, text, *args, **kwargs)

    monkeypatch.setattr(ImageDraw.ImageDraw, "text", capture)
    plan = dict(
        local_date="2026-10-08",
        location_label="COLORADO",
        seed="header-clear",
        policy=policy,
        artworks=[art],
        inputs={
            "open_meteo": {
                "local_date": "2026-10-08",
                "values": {
                    "weather_code": 1,
                    "temperature_2m_max": 40,
                    "temperature_2m_min": -30,
                    "wind_speed_10m_max": 0,
                },
            }
        },
    )
    render.compose(service.settings.art_dir, art, plan, tmp_path / "clear.png")
    assert len(header_boxes) == 2
    weather, location = header_boxes
    assert location[2] + 32 < weather[0]  # Includes the weather icon and a clear gap.
    for left, top, right, bottom in header_boxes:
        assert 12 <= left < right <= 788 and 10 <= top < bottom <= 42
        assert bottom - top >= 12  # Legible letter height on the physical panel.
