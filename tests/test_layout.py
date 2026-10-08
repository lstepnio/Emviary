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
    for point in ((60, 39), (400, 415), (400, 200)):
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
    assert ink(400, 415) == 0
    assert ink(70, 39) == 1
    assert ink(65, 39) == 3  # Colored content is not recolored.
    assert ink(400, 200) == 3  # Bird-cell pixels keep the color conversion.
