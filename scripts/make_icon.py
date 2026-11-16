"""Draw the DORA desktop icon (.ico with several sizes). No external assets.

    python scripts/make_icon.py data/dora.ico
"""

from __future__ import annotations

import sys
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont

ACCENT = (35, 70, 110, 255)  # --accent from web/static/app.css
LIGHT = (255, 255, 255, 255)
GOLD = (233, 196, 106, 255)
SIZES = [16, 24, 32, 48, 64, 128, 256]


def _font(size: int) -> ImageFont.ImageFont:
    for name in ("segoeuib.ttf", "arialbd.ttf", "DejaVuSans-Bold.ttf"):
        try:
            return ImageFont.truetype(name, size)
        except OSError:
            continue
    return ImageFont.load_default()


def draw(size: int = 256) -> Image.Image:
    img = Image.new("RGBA", (size, size), (0, 0, 0, 0))
    d = ImageDraw.Draw(img)
    pad = size // 16
    d.rounded_rectangle([pad, pad, size - pad, size - pad], radius=size // 5, fill=ACCENT)
    # Document sheet with a folded corner
    left, top, right, bottom = size * 0.26, size * 0.17, size * 0.74, size * 0.62
    fold = size * 0.11
    d.polygon([(left, top), (right - fold, top), (right, top + fold), (right, bottom), (left, bottom)], fill=LIGHT)
    d.polygon([(right - fold, top), (right - fold, top + fold), (right, top + fold)], fill=(200, 210, 222, 255))
    for i in range(3):  # text lines
        y = top + size * (0.12 + i * 0.09)
        d.rounded_rectangle([left + size * 0.06, y, right - size * 0.08, y + size * 0.035],
                            radius=size // 64, fill=(170, 184, 202, 255))
    # Word mark
    font = _font(int(size * 0.24))
    text = "DORA"
    box = d.textbbox((0, 0), text, font=font)
    w, h = box[2] - box[0], box[3] - box[1]
    d.text(((size - w) / 2 - box[0], size * 0.83 - h - box[1]), text, font=font, fill=GOLD)
    return img


def main() -> int:
    out = Path(sys.argv[1] if len(sys.argv) > 1 else "data/dora.ico")
    out.parent.mkdir(parents=True, exist_ok=True)
    draw(256).save(out, format="ICO", sizes=[(s, s) for s in SIZES])
    print(out)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
