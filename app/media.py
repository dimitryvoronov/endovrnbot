"""Store uploaded meal photos, shrunk + recompressed to JPEG to save disk."""
import uuid
from io import BytesIO
from pathlib import Path

from .config import MEDIA_DIR, PHOTO_MAX_SIDE, PHOTO_QUALITY

MAX_UPLOAD_BYTES = 20 * 1024 * 1024


def _shrink(raw: bytes) -> bytes | None:
    try:
        from PIL import Image, ImageOps

        im = Image.open(BytesIO(raw))
        im = ImageOps.exif_transpose(im)          # honour phone rotation
        im.thumbnail((PHOTO_MAX_SIDE, PHOTO_MAX_SIDE))  # keeps aspect, only downscales
        if im.mode not in ("RGB", "L"):
            im = im.convert("RGB")
        out = BytesIO()
        im.save(out, format="JPEG", quality=PHOTO_QUALITY, optimize=True, progressive=True)
        return out.getvalue()
    except Exception:
        return None                               # not a Pillow-decodable image (HEIC, ...)


def save_upload(raw: bytes, orig_name: str = "") -> str | None:
    """Write one photo to MEDIA_DIR; return its filename, or None if rejected."""
    if not raw or len(raw) > MAX_UPLOAD_BYTES:
        return None
    data = _shrink(raw)
    ext = ".jpg"
    if data is None:                              # keep the original if we can't decode it
        data = raw
        ext = (Path(orig_name).suffix.lower() or ".bin")[:5]
    name = f"{uuid.uuid4().hex}{ext}"
    (MEDIA_DIR / name).write_bytes(data)
    return name
