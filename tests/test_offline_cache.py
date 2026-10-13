import base64
import copy
import gzip
import hashlib
import json
import zlib

import pytest
from fastapi.testclient import TestClient
from PIL import Image, ImageChops

from emviary import render
from emviary.api import create_app
from emviary.diagnostics import parse_metrics
from emviary.offline_cache import extract_patch, offline_header, valid_patch


def decode(value):
    return json.loads(base64.b64decode(value))


def test_opt_in_header_preserves_legacy_bytes_and_digest(service, frame):
    identifier, token = frame
    record = service.prepare(identifier, "2026-10-08")
    with TestClient(create_app(service, schedule=False)) as client:
        headers = {"Authorization": f"Bearer {token}"}
        legacy = client.get("/v1/image", headers=headers)
        response = client.get("/v1/image", headers={**headers, "X-Emviary-Offline-Version": "1"})
        assert "x-emviary-offline" not in legacy.headers
        assert response.content == legacy.content
        value = decode(response.headers["x-emviary-offline"])
        assert value["sha"] == hashlib.sha256(response.content).hexdigest()
        assert value["id"] == str(record["id"])
        assert value["eligible"] and value["season"] == "autumn"
        assert len(response.headers["x-emviary-offline"]) <= 4096
        assert len(zlib.decompress(base64.b64decode(value["patch"]["z"]))) == 580 * 36 // 2
        unchanged = client.get(
            "/v1/image",
            headers={
                **headers,
                "X-Emviary-Offline-Version": "1",
                "If-None-Match": response.headers["etag"],
            },
        )
        assert unchanged.status_code == 304
        assert "x-emviary-offline" not in unchanged.headers


@pytest.mark.parametrize(
    "field,value",
    [
        ("special_day", {"label": "Birthday"}),
        ("special_day_test", True),
        ("content_category", "special_day"),
    ],
)
def test_special_days_explicitly_excluded(service, frame, field, value):
    record = dict(service.prepare(frame[0], "2026-10-08"))
    plan = json.loads(record["manifest"])
    plan[field] = value
    record["manifest"] = json.dumps(plan)
    assert decode(offline_header(record)) == {"v": 1, "eligible": False}


def test_old_render_missing_patch_and_event_art_never_admitted(service, frame):
    record = dict(service.prepare(frame[0], "2026-10-08"))
    plan = json.loads(record["manifest"])
    plan["artworks"][0]["event_only"] = True
    record["manifest"] = json.dumps(plan)
    assert not decode(offline_header(record))["eligible"]
    plan["artworks"][0].pop("event_only")
    plan.pop("offline_patch")
    record["manifest"] = json.dumps(plan)
    assert offline_header(record) is None


@pytest.mark.parametrize("code", [0, 3, 61, 71, 95])
def test_weather_all_inside_patch_and_patch_restores_exact_neutral_header(
    service, frame, tmp_path, code
):
    record = service.prepare(frame[0], "2026-10-08")
    plan = json.loads(record["manifest"])
    plan["inputs"]["open_meteo"] = {
        "local_date": "2026-10-08",
        "values": {
            "weather_code": code,
            "daylight_weather_code": code,
            "temperature_2m_min": 2,
            "temperature_2m_max": 25,
            "snowfall_sum": 2 if code == 71 else 0,
            "precipitation_probability_max": 90 if code > 3 else 0,
            "wind_speed_10m_max": 15,
        },
    }
    plan["policy"].update(
        weather_cues=True,
        show_location_name=True,
        show_weather_icon=True,
        show_weather_condition=True,
        show_forecast_temperatures=True,
    )
    neutral_plan = copy.deepcopy(plan)
    neutral_plan["policy"]["weather_cues"] = False
    weather, neutral = tmp_path / "weather.png", tmp_path / "neutral.png"
    render.compose(service.settings.art_dir, plan["artwork"], plan, weather)
    render.compose(service.settings.art_dir, plan["artwork"], neutral_plan, neutral)
    with Image.open(weather) as a, Image.open(neutral) as b:
        box = ImageChops.difference(a, b).getbbox()
        assert box is not None
        assert box[0] >= 200 and box[1] >= 10 and box[2] <= 780 and box[3] <= 46
    # Use the same exact quantization as production neutral graphics.
    target = tmp_path / "panel.epdgz"
    target.write_bytes(gzip.compress(bytes([0x66]) * 192000, mtime=0))
    render.preserve_neutral_graphics(neutral, target)
    raw = gzip.decompress(target.read_bytes())
    expected = b"".join(raw[y * 400 + 100 : y * 400 + 390] for y in range(10, 46))
    patch = extract_patch(target)
    assert zlib.decompress(base64.b64decode(patch["z"])) == expected


def test_invalid_patch_and_inflate_bomb_rejected():
    patch = {
        "x": 200,
        "y": 10,
        "w": 580,
        "h": 36,
        "z": base64.b64encode(zlib.compress(b"\x11" * 10440)).decode(),
    }
    assert valid_patch(patch)
    assert not valid_patch({**patch, "w": 581})
    assert not valid_patch({**patch, "x": 799})
    assert not valid_patch(
        {**patch, "z": base64.b64encode(zlib.compress(b"\x11" * 65537)).decode()}
    )
    assert not valid_patch(
        {**patch, "z": base64.b64encode(zlib.compress(b"\x44" * 10440)).decode()}
    )


def test_offline_metrics_are_bounded():
    metrics = {
        "offline_mode": True,
        "offline_image_id": 12,
        "offline_cache_count": 4,
        "offline_cache_bytes": 32000,
        "offline_rotations": 3,
    }
    assert parse_metrics(json.dumps(metrics)) == metrics
    assert parse_metrics(json.dumps({**metrics, "offline_cache_count": 257})) is None


def test_exact_patch_preserves_six_color_palette_pixels(tmp_path):
    # A future colored header or overlapping colored artwork must not be erased
    # or converted into grayscale by the offline metadata path.
    target = tmp_path / "neutral.epdgz"
    raw = bytearray([0x11] * 192000)
    row = bytes([0x02, 0x35, 0x61]) * 96 + bytes([0x02, 0x35])
    assert len(row) == 290
    raw[10 * 400 + 100 : 10 * 400 + 390] = row
    target.write_bytes(gzip.compress(raw, mtime=0))
    patch = extract_patch(target)
    tile = zlib.decompress(base64.b64decode(patch["z"]))
    assert tile[:290] == row
    assert set(n for b in tile for n in (b >> 4, b & 15)) == {0, 1, 2, 3, 5, 6}


def test_optional_neutral_conversion_failure_preserves_normal_delivery(service, frame):
    converter = service.converter
    calls = []

    def neutral_failure(source, *args):
        calls.append(source.name)
        if source.name == "neutral.png":
            raise TimeoutError("neutral conversion timed out")
        return converter(source, *args)

    service.converter = neutral_failure
    record = service.prepare(frame[0], "2026-10-08")
    assert calls == ["neutral.png", "master.png"]
    assert service.cache_path(record["path"]).is_file()
    assert "offline_patch" not in json.loads(record["manifest"])
    assert offline_header(record) is None


def test_owner_health_offline_inventory_is_last_reported_not_live(service, frame):
    from emviary.diagnostics import diagnostics_section
    from emviary.owner import escape

    service.store.device_sample(
        frame[0],
        {
            "offline_mode": True,
            "offline_image_id": 12,
            "offline_cache_count": 4,
            "offline_cache_bytes": 32000,
            "offline_rotations": 3,
        },
    )
    content = diagnostics_section(service.store, frame[0], escape)
    assert "Offline library" in content and "4 pictures" in content
    assert "Last reported: Cached artwork" in content
    assert "3 offline rotations" in content
    assert "Updates on the next connection" in content
