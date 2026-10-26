"""
rt.llm.decision_images
Immagini per il modello decisionale: OpenRouter le vuole dentro `state` come parti image_url
con data URL base64. Jev accetta solo PNG e JPEG con ogni lato tra 280 e 1568 px e non applica
l'orientamento EXIF, quindi l'immagine si normalizza qui.
"""
import base64
import io
from typing import Any, Dict

MIN_SIDE = 280
MAX_SIDE = 1568
MAX_BYTES = 8 * 1024 * 1024


def _encode(image, fmt: str) -> bytes:
    out = io.BytesIO()
    if fmt == "JPEG":
        image.save(out, "JPEG", quality=85, optimize=True)
    else:
        image.save(out, "PNG", optimize=True)
    return out.getvalue()


def normalize_image(data: bytes) -> tuple[bytes, str]:
    """(byte, mime) pronti per Jev: EXIF applicato, niente alpha, lato lungo ≤1568, ogni lato
    ≥280 con un bordo bianco (mai ingrandita). PNG per le pagine, JPEG per le foto."""
    from PIL import Image, ImageOps
    with Image.open(io.BytesIO(data)) as source:
        photo = (source.format or "").upper() in ("JPEG", "MPO", "HEIF", "HEIC", "WEBP")
        image = ImageOps.exif_transpose(source)
        image.load()
    if image.mode in ("RGBA", "LA", "P", "PA") or "transparency" in image.info:
        rgba = image.convert("RGBA")
        image = Image.new("RGB", rgba.size, "white")
        image.paste(rgba, mask=rgba.getchannel("A"))
    elif image.mode != "RGB":
        image = image.convert("RGB")
    if max(image.size) > MAX_SIDE:
        image.thumbnail((MAX_SIDE, MAX_SIDE), Image.LANCZOS)
    width, height = image.size
    if width < MIN_SIDE or height < MIN_SIDE:
        canvas = Image.new("RGB", (max(width, MIN_SIDE), max(height, MIN_SIDE)), "white")
        canvas.paste(image, ((canvas.width - width) // 2, (canvas.height - height) // 2))
        image = canvas
    fmt = "JPEG" if photo else "PNG"
    encoded = _encode(image, fmt)
    if len(encoded) > MAX_BYTES and fmt == "PNG":
        fmt, encoded = "JPEG", _encode(image, "JPEG")
    return encoded, "image/jpeg" if fmt == "JPEG" else "image/png"


def image_part(data: bytes) -> Dict[str, Any]:
    encoded, mime = normalize_image(data)
    url = f"data:{mime};base64,{base64.b64encode(encoded).decode('ascii')}"
    return {"type": "image_url", "image_url": {"url": url}}
