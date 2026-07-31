#!/usr/bin/env python3
# /// script
# requires-python = ">=3.9"
# dependencies = [
#     "Pillow>=10.0",
# ]
# ///
"""
Showcase Image Generator
Creates a preview image showing up to 3 final App Store screenshots
side-by-side on a white background with an optional GitHub link at the bottom.

The caption (the GitHub URL) is chrome around the screenshots, not headline
text, so it deliberately ignores $ASO_FONT — that variable is a per-locale
headline font for compose.py and would put, say, a Thai face on a Latin URL.
The caption always uses the first available platform default.
"""

import argparse
import os
from PIL import Image, ImageDraw, ImageFont

# ── Layout ──────────────────────────────────────────────────────────
PADDING = 60
GAP = 40
BOTTOM_BAR_H = 100


def _resolve_font():
    """First existing per-platform default. Intentionally ignores $ASO_FONT."""
    candidates = [
        "/Library/Fonts/SF-Pro-Display-Regular.otf",
        "/System/Library/Fonts/SFNS.ttf",
        "/System/Library/Fonts/Supplemental/Arial.ttf",
        "/usr/share/fonts/truetype/noto/NotoSans-Regular.ttf",
        "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
        os.path.join(os.environ.get("WINDIR", r"C:\Windows"), "Fonts", "arial.ttf"),
    ]
    for path in candidates:
        if path and os.path.isfile(path):
            return path
    raise SystemExit(
        "No usable caption font found on this system. Install a basic sans "
        "(e.g. `sudo apt install fonts-dejavu-core` on Linux).")


FONT_PATH = _resolve_font()
FONT_SIZE_MAX = 48
FONT_SIZE_MIN = 16
TEXT_COLOUR = "#000000"
BG_COLOUR = (255, 255, 255)


def fit_text_font(text, max_w, size_max, size_min):
    """Return the largest font size where text fits within max_w."""
    dummy = ImageDraw.Draw(Image.new("RGB", (1, 1)))
    for size in range(size_max, size_min - 1, -2):
        try:
            font = ImageFont.truetype(FONT_PATH, size)
        except OSError:
            font = ImageFont.load_default()
            return font
        bbox = dummy.textbbox((0, 0), text, font=font)
        if (bbox[2] - bbox[0]) <= max_w:
            return font
    return ImageFont.truetype(FONT_PATH, size_min)


def create_showcase(screenshots, output_path, github_url=None):
    # Load screenshots
    images = [Image.open(p).convert("RGBA") for p in screenshots]

    # Scale all to same height
    target_h = 800
    scaled = []
    for img in images:
        ratio = target_h / img.height
        scaled.append(img.resize((int(img.width * ratio), target_h), Image.LANCZOS))

    # Calculate canvas size
    total_w = sum(s.width for s in scaled) + GAP * (len(scaled) - 1) + PADDING * 2
    total_h = target_h + PADDING * 2 + (BOTTOM_BAR_H if github_url else 0)

    canvas = Image.new("RGB", (total_w, total_h), BG_COLOUR)

    # Place screenshots
    x = PADDING
    for s in scaled:
        canvas.paste(s, (x, PADDING), s if s.mode == "RGBA" else None)
        x += s.width + GAP

    # Add GitHub URL text
    if github_url:
        draw = ImageDraw.Draw(canvas)
        max_text_w = total_w - PADDING * 2
        font = fit_text_font(github_url, max_text_w, FONT_SIZE_MAX, FONT_SIZE_MIN)

        text_y = PADDING + target_h + (BOTTOM_BAR_H // 2)
        draw.text(
            (total_w // 2, text_y),
            github_url,
            fill=TEXT_COLOUR,
            font=font,
            anchor="mm",
        )

    canvas.save(output_path, "PNG")
    print(f"✓ {output_path} ({total_w}×{total_h})")


def main():
    p = argparse.ArgumentParser(description="Generate showcase image")
    p.add_argument(
        "--screenshots",
        nargs="+",
        required=True,
        help="Paths to the final screenshot images, .jpg or .png (up to 3)",
    )
    p.add_argument("--output", required=True, help="Output file path")
    p.add_argument("--github", default=None, help="GitHub URL to display at bottom")
    args = p.parse_args()

    create_showcase(args.screenshots, args.output, args.github)


if __name__ == "__main__":
    main()
