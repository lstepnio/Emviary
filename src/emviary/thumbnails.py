"""Bounded web-only thumbnails. Frame rendering always uses original masters."""

from functools import lru_cache
from hashlib import sha256
from io import BytesIO

from PIL import Image, ImageOps


@lru_cache(maxsize=64)
def thumbnail(path, modified, size):
    # Metadata keys invalidate the cache when a master is replaced.
    with Image.open(path) as source:
        image = ImageOps.exif_transpose(source).convert("RGBA")
        image.thumbnail((480, 360), Image.Resampling.LANCZOS)
        background = Image.new("RGB", image.size, "white")
        background.paste(image, mask=image.getchannel("A"))
        output = BytesIO()
        background.save(output, format="JPEG", quality=82, optimize=True)
    data = output.getvalue()
    return data, '"' + sha256(data).hexdigest() + '"'
