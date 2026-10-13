import hashlib
import json
import struct

import pytest
from fastapi.testclient import TestClient
from test_owner import sign_in

from emviary import usb_recovery
from emviary.api import create_app


def test_usb_bundle_is_private_complete_and_keeps_nvs_regions_untouched(
    service, frame, tmp_path, monkeypatch
):
    anonymous = TestClient(create_app(service, schedule=False))
    base = "/manage/usb-recovery"
    assert anonymous.get(base + "/manifest").status_code == 401
    assert anonymous.get(base + "/assets/recovery.js").status_code == 401
    assert anonymous.get(base + "/v0.8.6/application.bin").status_code == 401
    client, _ = sign_in(service, tmp_path, monkeypatch)
    before = service.store.frame(frame[0])["policy"]
    response = client.get(base + "/manifest")
    assert response.status_code == 200 and response.headers["cache-control"] == "no-store"
    manifest = response.json()
    assert manifest["board"] == "seeedstudio_reterminal_e1002"
    assert manifest["chip"] == "ESP32-S3" and manifest["version"] == "v0.8.6"
    assert "token" not in json.dumps(manifest) and "password" not in json.dumps(manifest)
    for part in manifest["parts"]:
        data = client.get(part["url"])
        assert data.status_code == 200
        assert len(data.content) == part["size"]
        assert hashlib.sha256(data.content).hexdigest() == part["sha256"]
        end = part["address"] + part["size"]
        assert end <= 0x9000 or part["address"] >= 0xF000  # NVS preserved.
        assert end <= 0x720000  # Filesystem preserved.
    table = client.get(base + "/v0.8.6/partition-table.bin").content
    partitions = {}
    for offset in range(0, 32 * 16, 32):
        magic, kind, subtype, address, size, name, flags = struct.unpack(
            "<HBBII16sI", table[offset : offset + 32]
        )
        if magic != 0x50AA:
            break
        partitions[name.rstrip(b"\0").decode()] = (address, size)
    assert partitions["nvs"] == (0x9000, 0x6000)
    assert partitions["otadata"] == (0xF000, 0x2000)
    assert partitions["ota_0"] == (0x20000, 0x380000)
    assert partitions["storage"][0] == 0x720000
    assert client.get(base + "/v0.8.6/ota-data.bin").content == b"\xff" * 8192
    assert client.get(base + "/v0.8.6/other.bin").status_code == 404
    assert client.get(base + "/v0.8.2/application.bin").status_code == 404
    assert (
        client.get(base + "/assets/recovery.js")
        .headers["content-type"]
        .startswith("text/javascript")
    )
    assert service.store.frame(frame[0])["policy"] == before
    page = client.get("/manage/recovery?frame=" + frame[0]).text
    assert "Recover your frame" in page and "Check and recover" in page
    assert "data-usb-speed" in page
    assert "USB connection instructions" in page and "Do not select Bluetooth" in page
    assert "data-usb-start disabled" in page and "replace_local_settings" in page


def test_usb_manifest_refuses_corrupt_packaged_files(tmp_path, monkeypatch):
    root = tmp_path / "corrupt"
    root.mkdir()
    manifest = json.loads((usb_recovery.ROOT / "manifest.json").read_text())
    (root / "manifest.json").write_text(json.dumps(manifest))
    (root / "v0.8.6").mkdir()
    (root / "v0.8.6/bootloader.bin").write_bytes(b"invalid")
    usb_recovery.recovery_manifest.cache_clear()
    monkeypatch.setattr(usb_recovery, "ROOT", root)
    try:
        with pytest.raises(ValueError):
            usb_recovery.recovery_manifest()
    finally:
        usb_recovery.recovery_manifest.cache_clear()
