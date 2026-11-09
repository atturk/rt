"""Genera le icone dei documenti di RT (rt-lezioni, rt-collezione, rt-orario) da rt.png.

Produce i file .icns per macOS e .ico per Windows in packaging/icons/.
"""
import os
import shutil
import subprocess
import tempfile
from PIL import Image, ImageDraw

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
ICONS_DIR = os.path.join(ROOT, "packaging", "icons")
RT_PNG = os.path.join(ICONS_DIR, "rt.png")

DOCUMENT_TYPES = [
    "rt-lezioni",
    "rt-collezione",
    "rt-orario",
]


def create_document_image(base_png: str) -> Image.Image:
    """Crea una composizione 1024x1024: foglio bianco con angolo piegato e logo RT."""
    canvas = Image.new("RGBA", (1024, 1024), (0, 0, 0, 0))
    shadow = Image.new("RGBA", (1024, 1024), (0, 0, 0, 0))
    sdraw = ImageDraw.Draw(shadow)

    x0, y0, x1, y1 = 200, 100, 824, 924
    sdraw.rounded_rectangle([x0 + 6, y0 + 10, x1 + 6, y1 + 10], radius=36, fill=(0, 0, 0, 45))

    draw = ImageDraw.Draw(canvas)
    draw.rounded_rectangle([x0, y0, x1, y1], radius=36, fill=(255, 255, 255, 255), outline=(215, 218, 224, 255), width=6)

    fold = 140
    mask = Image.new("L", (1024, 1024), 255)
    mdraw = ImageDraw.Draw(mask)
    mdraw.polygon([(x1 - fold, y0), (x1 + 10, y0), (x1 + 10, y0 + fold + 10), (x1, y0 + fold)], fill=0)
    canvas.putalpha(Image.composite(canvas.getchannel("A"), mask, mask))

    draw = ImageDraw.Draw(canvas)
    draw.polygon([(x1 - fold, y0), (x1 - fold, y0 + fold), (x1, y0 + fold)], fill=(238, 240, 245, 255), outline=(200, 204, 212, 255), width=4)

    rt_logo = Image.open(base_png).convert("RGBA")
    logo_size = 460
    rt_resized = rt_logo.resize((logo_size, logo_size), Image.Resampling.LANCZOS)
    canvas.alpha_composite(rt_resized, (x0 + (x1 - x0 - logo_size) // 2, y0 + (y1 - y0 - logo_size) // 2 + 30))

    return Image.alpha_composite(shadow, canvas)


def build_icns(img: Image.Image, out_path: str) -> None:
    if shutil.which("iconutil"):
        with tempfile.TemporaryDirectory() as tmpdir:
            iconset = os.path.join(tmpdir, "icon.iconset")
            os.makedirs(iconset)
            for s in (16, 32, 128, 256, 512):
                img.resize((s, s), Image.Resampling.LANCZOS).save(os.path.join(iconset, f"icon_{s}x{s}.png"))
                img.resize((s * 2, s * 2), Image.Resampling.LANCZOS).save(os.path.join(iconset, f"icon_{s}x{s}@2x.png"))
            subprocess.run(["iconutil", "-c", "icns", iconset, "-o", out_path], check=True)
    else:
        # Fallback Pillow
        img.save(out_path, format="ICNS")


def build_ico(img: Image.Image, out_path: str) -> None:
    img.save(out_path, format="ICO", sizes=[(16, 16), (32, 32), (48, 48), (64, 64), (128, 128), (256, 256)])


def main() -> None:
    if not os.path.isfile(RT_PNG):
        raise SystemExit(f"Logo {RT_PNG} non trovato.")

    img = create_document_image(RT_PNG)

    for doc_name in DOCUMENT_TYPES:
        icns_path = os.path.join(ICONS_DIR, f"{doc_name}.icns")
        ico_path = os.path.join(ICONS_DIR, f"{doc_name}.ico")
        print(f"Generazione {doc_name}.icns e {doc_name}.ico...")
        build_icns(img, icns_path)
        build_ico(img, ico_path)

    print("Completato con successo!")


if __name__ == "__main__":
    main()
