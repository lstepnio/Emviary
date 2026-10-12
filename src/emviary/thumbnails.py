"""Persistent web thumbnails with at most two concurrent full-image decodes."""

import json
import os
import tempfile
from contextlib import closing
from hashlib import sha256
from pathlib import Path
from threading import BoundedSemaphore

from PIL import Image, ImageOps

# One application worker owns this gate; do not multiply workers without a
# shared queue. Hits never enter the decode gate and never open an artwork.
_DECODE_SLOTS = BoundedSemaphore(2)
_RECIPE = "jpeg-480x360-lanczos-q82-optimize-v1"


def _render_thumbnail(source_path, target):
    # Keep the original operations and encoding parameters, including EXIF
    # handling and white alpha compositing. Close each large buffer promptly.
    with closing(Image.open(source_path)) as source:
        with closing(ImageOps.exif_transpose(source)) as oriented:
            with closing(oriented.convert("RGBA")) as image:
                image.thumbnail((480, 360), Image.Resampling.LANCZOS)
                with closing(Image.new("RGB", image.size, "white")) as background:
                    with closing(image.getchannel("A")) as alpha:
                        background.paste(image, mask=alpha)
                    background.save(target, format="JPEG", quality=82, optimize=True)


def _file_tag(path):
    digest = sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(65536), b""):
            digest.update(block)
    return '"' + digest.hexdigest() + '"'


def thumbnail_file(path, modified, size, cache_dir):
    """Return a cached file and byte-derived ETag, surviving process restarts."""
    identity = json.dumps([_RECIPE, str(Path(path).resolve()), modified, size])
    key = sha256(identity.encode()).hexdigest()
    directory = Path(cache_dir)
    directory.mkdir(parents=True, exist_ok=True)
    target = directory / (key + ".jpg")
    if not target.is_file():
        with _DECODE_SLOTS:
            # Another caller may have filled this entry while we waited.
            if not target.is_file():
                temporary = None
                try:
                    with tempfile.NamedTemporaryFile(
                        dir=directory, prefix="thumbnail-", suffix=".tmp", delete=False
                    ) as handle:
                        temporary = Path(handle.name)
                        _render_thumbnail(path, handle)
                        handle.flush()
                        os.fsync(handle.fileno())
                    temporary.replace(target)
                finally:
                    if temporary is not None:
                        temporary.unlink(missing_ok=True)
    return target, _file_tag(target)
