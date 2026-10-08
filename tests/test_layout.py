import gzip

from PIL import Image

from einkartifact import render


def test_panel_limits_and_species_rules(service, tmp_path):
    policy = service.settings.config.frame_defaults.model_dump()
    outcomes = set()
    for number in range(20):
        selected = render.choose_artworks(
            service.settings.artworks, "2026-10-08", {}, [], str(number), policy
        )
        outcomes.add(len(selected))
        assert len(selected) <= 2
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
    assert outcomes == {1, 2}
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
