import gzip
import hashlib
from pathlib import Path

import pytest
from PIL import Image

from einkartifact.service import Service
from einkartifact.settings import Settings

ROOT = Path(__file__).resolve().parents[1]


class OfflineProviders:
    def __init__(self):
        self.calls = 0

    def inputs(self, *args, **kwargs):
        self.calls += 1
        return {}


def fake_converter(source, target, preview, policy, timeout):
    digest = hashlib.sha256(source.read_bytes()).digest()
    inks = [0, 1, 2, 3, 5, 6]
    pattern = bytes((inks[n % 6] << 4) | inks[(n // 6) % 6] for n in digest)
    with gzip.GzipFile(filename=str(target), mode="wb", mtime=0) as writer:
        writer.write(pattern * (192000 // len(pattern)))
    with Image.open(source) as image:
        image.convert("RGB").save(preview)


@pytest.fixture
def service(tmp_path):
    settings = Settings(
        config_path=ROOT / "deployment/site.example.json",
        data_dir=tmp_path / "data",
        art_dir=ROOT / "art",
        backup_dir=tmp_path / "backups",
    )
    return Service(settings, providers=OfflineProviders(), converter=fake_converter)


@pytest.fixture
def frame(service):
    policy = service.settings.config.frame_defaults
    token = service.store.add_frame("test-frame", policy)
    return "test-frame", token
