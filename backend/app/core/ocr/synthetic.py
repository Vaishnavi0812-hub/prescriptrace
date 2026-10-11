"""Synthetic printed prescriptions for tests and the OCR evaluation (no real patient data).

All names below are invented. Medicine lines use real brand/generic names so recognition can be
checked end to end.
"""

from __future__ import annotations

import io
import random
from pathlib import Path

from PIL import Image, ImageDraw, ImageFilter, ImageFont

FONT_DIR = Path("/usr/share/fonts/truetype/dejavu")
HEADER = [
    "City Care Clinic, 12 Market Road",
    "Dr. A. Example, MBBS   Reg No 00000",
    "Patient: Test Person   Age: 54   Sex: F",
    "Date: 01/10/2026",
    "Rx",
]
FOOTER = ["Review after 1 week", "Signature"]


def render(
    medicines: list[str],
    *,
    rotate: float = 0.0,
    blur: float = 0.0,
    noise: float = 0.0,
    width: int = 1240,
    font_size: int = 34,
    seed: int = 0,
    serif: bool = False,
    font_path: Path | None = None,
) -> bytes:
    """Render a prescription page and return PNG bytes. `font_path` overrides the font (the
    evaluation uses handwriting-style fonts as a stand-in for handwriting)."""
    font_file = "DejaVuSerif.ttf" if serif else "DejaVuSans.ttf"
    font = ImageFont.truetype(str(font_path or FONT_DIR / font_file), font_size)
    lines = HEADER + [f"{i}. {m}" for i, m in enumerate(medicines, 1)] + [""] + FOOTER
    line_h = int(font_size * 1.8)
    height = 120 + line_h * len(lines)
    page = Image.new("L", (width, height), 250)
    draw = ImageDraw.Draw(page)
    for i, text in enumerate(lines):
        draw.text((80, 60 + i * line_h), text, fill=25, font=font)
    if noise:
        rng = random.Random(seed)  # noqa: S311 - image noise, not security
        pixels = page.load()
        assert pixels is not None
        for _ in range(int(width * height * noise)):
            x, y = rng.randrange(width), rng.randrange(height)
            pixels[x, y] = rng.choice((0, 255))
    if blur:
        page = page.filter(ImageFilter.GaussianBlur(blur))
    if rotate:
        page = page.rotate(rotate, expand=True, fillcolor=250, resample=Image.Resampling.BICUBIC)
    buffer = io.BytesIO()
    page.save(buffer, format="PNG")
    return buffer.getvalue()
