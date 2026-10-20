#!/usr/bin/env python3
"""
scripts/make_dmg_background.py
Genera le immagini di sfondo per la finestra del DMG (1x e 2x):
  packaging/dmg/background.png    (660x400)
  packaging/dmg/background@2x.png (1320x800)

Lo sfondo contiene una freccia discreta tra le icone e tre istruzioni numerate
per l'installazione e la prima apertura su macOS (Apri comunque).
"""
import os
import sys
from PIL import Image, ImageDraw, ImageFont

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
OUTPUT_DIR = os.path.join(ROOT, "packaging", "dmg")


def find_font(size: int):
    candidates = [
        "/System/Library/Fonts/SFCompact.ttf",
        "/System/Library/Fonts/Helvetica.ttc",
        "/System/Library/Fonts/Supplemental/Arial.ttf",
        "/Library/Fonts/Arial.ttf",
        "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
    ]
    for p in candidates:
        if os.path.isfile(p):
            try:
                return ImageFont.truetype(p, size)
            except Exception:
                pass
    return ImageFont.load_default()


def generate(out_dir: str = OUTPUT_DIR) -> tuple[str, str]:
    os.makedirs(out_dir, exist_ok=True)

    width_2x, height_2x = 1320, 800
    bg_color = "#f5f5f7"
    arrow_color = "#a1a1a6"
    text_color = "#3a3a3c"

    img_2x = Image.new("RGB", (width_2x, height_2x), color=bg_color)
    draw_2x = ImageDraw.Draw(img_2x)

    # Freccia sottile tra la posizione di RT.app (320, 300) e Applicazioni (1000, 300)
    line_y = 300
    arrow_start_x = 530
    arrow_end_x = 780
    draw_2x.line([(arrow_start_x, line_y), (arrow_end_x, line_y)], fill=arrow_color, width=4)
    draw_2x.polygon(
        [(arrow_end_x - 5, line_y - 14), (arrow_end_x + 20, line_y), (arrow_end_x - 5, line_y + 14)],
        fill=arrow_color,
    )

    # Istruzioni numerate in basso
    font_2x = find_font(27)
    lines = [
        "1.  Trascina RT in Applicazioni",
        "2.  Apri RT da Applicazioni",
        "3.  Impostazioni › Privacy e sicurezza › Apri comunque",
    ]

    bboxes = [draw_2x.textbbox((0, 0), l, font=font_2x) for l in lines]
    max_w = max(b[2] - b[0] for b in bboxes)
    start_x = (width_2x - max_w) // 2
    start_y = 540
    line_gap = 52

    for i, line in enumerate(lines):
        draw_2x.text((start_x, start_y + i * line_gap), line, fill=text_color, font=font_2x)

    path_2x = os.path.join(out_dir, "background@2x.png")
    path_1x = os.path.join(out_dir, "background.png")

    img_1x = img_2x.resize((width_2x // 2, height_2x // 2), Image.Resampling.LANCZOS)

    img_2x.save(path_2x)
    img_1x.save(path_1x)

    return path_1x, path_2x


if __name__ == "__main__":
    p1, p2 = generate()
    print(f"Creati:\n  {p1} ({Image.open(p1).size})\n  {p2} ({Image.open(p2).size})")
