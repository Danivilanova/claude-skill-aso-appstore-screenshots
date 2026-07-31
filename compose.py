#!/usr/bin/env python3
# /// script
# requires-python = ">=3.9"
# dependencies = [
#     "Pillow>=10.0",
# ]
# ///
"""
App Store Screenshot Composer
Composites headline text, device frame template, and app screenshot
into a pixel-perfect 1290×2796 App Store Connect image.

The device frame is positioned dynamically based on text height,
matching the proportions seen in professional App Store screenshots.

Font resolution order (highest priority first):
  1. --font <name-or-absolute-path>
  2. $ASO_FONT (absolute path, or a filename in the platform font dirs)
  3. The platform default (SF Pro Display Black / Noto Sans Black / Arial Bold)

If the resolved font lacks glyphs for the headline's script (CJK, Arabic,
Hebrew, Thai, Devanagari, …) a script-appropriate system font is substituted
automatically. Right-to-left scripts additionally need Pillow built with
libraqm for correct shaping — compose.py warns loudly when it is missing.
"""

import argparse
import os
import platform
import subprocess
import sys
import unicodedata
from PIL import Image, ImageDraw, ImageFont, ImageChops, features

# ── Canvas ──────────────────────────────────────────────────────────
CANVAS_W = 1290
CANVAS_H = 2796

# ── Device template constants (must match generate_frame.py) ───────
DEVICE_W = 1030
BEZEL = 15
SCREEN_W = DEVICE_W - 2 * BEZEL    # 1000
SCREEN_CORNER_R = 62

# ── Layout ──────────────────────────────────────────────────────────
DEVICE_Y = 720                       # device top position (fixed)
MIN_TEXT_DEVICE_GAP = 40             # minimum gap between text bottom and device top

# ── Typography ──────────────────────────────────────────────────────
VERB_SIZE_MAX = 256
VERB_SIZE_MIN = 150
DESC_SIZE_MAX = 124
DESC_SIZE_MIN = 80
VERB_DESC_GAP = 20
DESC_LINE_GAP = 24
MAX_VERB_LINES = 2
MAX_DESC_LINES = 3
TEXT_TOP = 200                       # y of the first headline line

# Horizontal safe area. The AI enhancement step generates at 9:16 and the
# result is cropped back to Apple's narrower ratio, which keeps ~82% of the
# width — so anything wider than this risks losing text to that crop.
# SKILL.md quotes the same 75% figure; keep the two in sync.
SAFE_W_FRACTION = 0.75
MAX_TEXT_W = int(CANVAS_W * SAFE_W_FRACTION)
MAX_VERB_W = int(CANVAS_W * SAFE_W_FRACTION)

FRAME_PATH = os.path.join(os.path.dirname(__file__), "assets", "device_frame.png")

# ── Cross-platform font resolution ─────────────────────────────────
_SYSTEM = platform.system()

if _SYSTEM == "Darwin":
    _FONT_DIRS = [
        "/Library/Fonts",
        os.path.expanduser("~/Library/Fonts"),
        "/System/Library/Fonts",
        "/System/Library/Fonts/Supplemental",
    ]
    _DEFAULT_FONT = "SF-Pro-Display-Black.otf"
elif _SYSTEM == "Linux":
    _FONT_DIRS = [
        "/usr/share/fonts/truetype/noto",
        "/usr/share/fonts/truetype",
        "/usr/share/fonts",
        "/usr/local/share/fonts",
        os.path.expanduser("~/.local/share/fonts"),
    ]
    _DEFAULT_FONT = "NotoSans-Black.ttf"
else:  # Windows
    _FONT_DIRS = [os.path.join(os.environ.get("WINDIR", r"C:\Windows"), "Fonts")]
    _DEFAULT_FONT = "arialbd.ttf"


# ── Per-script fallback fonts ──────────────────────────────────────
# Used automatically when the selected font has no glyphs for the headline.
# First entry that resolves on this machine wins.
_SCRIPT_FONTS = {
    "cjk": {
        "Darwin": ["ヒラギノ角ゴシック W8.ttc", "ヒラギノ角ゴシック W6.ttc",
                   "Hiragino Sans GB.ttc", "PingFang.ttc",
                   "AppleSDGothicNeo.ttc", "STHeiti Medium.ttc"],
        "Linux": ["NotoSansCJK-Black.ttc", "NotoSansCJK-Bold.ttc",
                  "NotoSansCJKsc-Bold.otf", "NotoSansCJKjp-Bold.otf"],
        "Windows": ["msyhbd.ttc", "meiryob.ttc", "malgunbd.ttf"],
    },
    "arabic": {
        "Darwin": ["SFArabic.ttf", "GeezaPro.ttc", "Baghdad.ttc",
                   "Arial Unicode.ttf"],
        "Linux": ["NotoNaskhArabic-Bold.ttf", "NotoSansArabic-Black.ttf",
                  "NotoSansArabic-Bold.ttf"],
        "Windows": ["arabtype.ttf", "trebucbd.ttf"],
    },
    "hebrew": {
        "Darwin": ["SFHebrew.ttf", "ArialHB.ttc", "NewPeninimMT.ttc",
                   "Arial Unicode.ttf"],
        "Linux": ["NotoSansHebrew-Black.ttf", "NotoSansHebrew-Bold.ttf"],
        "Windows": ["ariblk.ttf", "arialbd.ttf"],
    },
    "thai": {
        "Darwin": ["ThonburiUI.ttc", "Thonburi.ttc", "Ayuthaya.ttf",
                   "Arial Unicode.ttf"],
        "Linux": ["NotoSansThai-Black.ttf", "NotoSansThai-Bold.ttf"],
        "Windows": ["leelawdb.ttf", "tahomabd.ttf"],
    },
    "devanagari": {
        "Darwin": ["SFIndia.ttc", "Devanagari Sangam MN.ttc", "Kohinoor.ttc",
                   "Arial Unicode.ttf"],
        "Linux": ["NotoSansDevanagari-Black.ttf", "NotoSansDevanagari-Bold.ttf"],
        "Windows": ["mangalb.ttf", "NirmalaB.ttf"],
    },
    "greek": {
        "Darwin": ["SF-Pro-Display-Black.otf", "HelveticaNeue.ttc", "Arial Black.ttf"],
        "Linux": ["NotoSans-Black.ttf", "DejaVuSans-Bold.ttf"],
        "Windows": ["ariblk.ttf", "arialbd.ttf"],
    },
    "cyrillic": {
        "Darwin": ["SF-Pro-Display-Black.otf", "Arial Black.ttf"],
        "Linux": ["NotoSans-Black.ttf", "DejaVuSans-Bold.ttf"],
        "Windows": ["ariblk.ttf", "arialbd.ttf"],
    },
}

# Scripts written right-to-left — these need libraqm for correct shaping.
_RTL_SCRIPTS = {"arabic", "hebrew"}


def _resolve_font(font_name, required=True):
    """Find a font file by name, searching platform-appropriate directories.

    Accepts either a bare filename (searched in platform font dirs) or a full
    absolute path. On Linux, falls back to ``fc-match`` if the file isn't
    found in the standard directories. Returns ``None`` instead of raising
    when ``required`` is False (used for optional per-script fallbacks).
    """
    if os.path.isabs(font_name):
        if os.path.isfile(font_name):
            return font_name
        if required:
            raise SystemExit(
                f"Font not found: {font_name}\n"
                f"Pass an existing file with --font, or set ASO_FONT to a bold "
                f"display .ttf/.otf."
            )
        return None
    for d in _FONT_DIRS:
        candidate = os.path.join(d, font_name)
        if os.path.isfile(candidate):
            return candidate
    # Linux fallback: ask fontconfig
    if _SYSTEM == "Linux":
        try:
            result = subprocess.run(
                ["fc-match", "-f", "%{file}", font_name],
                capture_output=True, text=True,
            )
            if result.returncode == 0 and os.path.isfile(result.stdout.strip()):
                return result.stdout.strip()
        except FileNotFoundError:
            pass
    if not required:
        return None
    raise SystemExit(
        f"Font '{font_name}' not found in: {', '.join(_FONT_DIRS)}. "
        f"Pass a full path with --font /path/to/font.ttf, or set ASO_FONT."
    )


def detect_script(text):
    """Return a coarse script key ('latin', 'cjk', 'arabic', …) for `text`."""
    prefixes = {
        "CJK": "cjk", "HIRAGANA": "cjk", "KATAKANA": "cjk", "HANGUL": "cjk",
        "ARABIC": "arabic", "HEBREW": "hebrew", "THAI": "thai",
        "DEVANAGARI": "devanagari", "GREEK": "greek", "CYRILLIC": "cyrillic",
    }
    for ch in text:
        if not ch.strip() or ch.isdigit():
            continue
        try:
            name = unicodedata.name(ch)
        except ValueError:
            continue
        for prefix, script in prefixes.items():
            if name.startswith(prefix):
                return script
    return "latin"


def _render_glyph(font, ch):
    """Rasterise a single character to raw bytes (for glyph comparison)."""
    img = Image.new("L", (96, 96), 0)
    ImageDraw.Draw(img).text((8, 8), ch, fill=255, font=font)
    return img.tobytes()


def _missing_glyphs(font_path, text):
    """Return the characters in `text` the font has no glyph for.

    Detected by comparing each character's rasterisation against that of a
    codepoint no font maps (a Unicode tag character) — i.e. the .notdef box.
    """
    probe = ImageFont.truetype(font_path, 48)
    notdef = _render_glyph(probe, "\U000e0002")
    missing = []
    for ch in sorted(set(text)):
        if not ch.strip():
            continue
        try:
            if _render_glyph(probe, ch) == notdef:
                missing.append(ch)
        except Exception:
            missing.append(ch)
    return missing


def pick_font(text, requested=None):
    """Resolve the headline font, substituting a script font when needed.

    Returns ``(font_path, script, substituted)``.
    """
    requested = requested or os.environ.get("ASO_FONT") or _DEFAULT_FONT
    font_path = _resolve_font(requested)
    script = detect_script(text)

    if not _missing_glyphs(font_path, text):
        return font_path, script, False

    for candidate in _SCRIPT_FONTS.get(script, {}).get(_SYSTEM, []):
        alt = _resolve_font(candidate, required=False)
        if alt and not _missing_glyphs(alt, text):
            print(
                f"⚠ '{os.path.basename(font_path)}' has no {script} glyphs — "
                f"using '{os.path.basename(alt)}' instead.",
                file=sys.stderr,
            )
            return alt, script, True

    print(
        f"⚠ '{os.path.basename(font_path)}' is missing glyphs for this "
        f"{script} headline and no fallback font was found on this system. "
        f"The text will render as tofu (□). Set ASO_FONT to a font that "
        f"covers {script}.",
        file=sys.stderr,
    )
    return font_path, script, False


def check_rtl_support(script):
    """Warn when an RTL headline is rendered without libraqm shaping."""
    if script not in _RTL_SCRIPTS:
        return True
    if features.check("raqm"):
        return True
    print(
        "⚠ RTL WARNING: this Pillow build has no libraqm, so Arabic/Hebrew "
        "text will NOT be shaped or reordered correctly (letters appear "
        "isolated and in visual reverse order). Install a Pillow build with "
        "libraqm (e.g. `pip install --upgrade --force-reinstall Pillow` on a "
        "system with libraqm, or `brew install libraqm` first on macOS) "
        "before shipping this locale.",
        file=sys.stderr,
    )
    return False


def hex_to_rgb(h):
    """Parse #RGB or #RRGGBB into an (r, g, b) tuple."""
    value = h.strip().lstrip("#")
    if len(value) == 3:
        value = "".join(ch * 2 for ch in value)      # #000 → #000000
    if len(value) != 6 or any(c not in "0123456789abcdefABCDEF" for c in value):
        raise SystemExit(
            f"✗ Invalid --bg value: '{h}'\n"
            f"  --bg must be a hex colour like #E31837 (or the short form #E13)."
        )
    return tuple(int(value[i : i + 2], 16) for i in (0, 2, 4))


# Scripts written without spaces: a whole headline arrives as one "word" and
# can only be wrapped between characters — which is how they are set anyway.
_NO_SPACE_SCRIPTS = {"cjk", "thai"}

# Minimal kinsoku shori: characters that must never open a line in Japanese
# typesetting — small kana, the prolonged sound mark, closing brackets and
# punctuation. When a character break lands in front of one of these, the
# break is retreated so the offending character stays on the previous line.
_KINSOKU_NO_START = set(
    "、。，．・：；！？ー〜…"          # punctuation and the prolonged sound mark
    "っゃゅょぁぃぅぇぉんゝゞ々"       # small hiragana + iteration marks
    "ッャュョァィゥェォヮヵヶヽヾ"     # small katakana (ェックする must not open)
    "」』）〕】》〉}]!?,.)"            # closing brackets
)


def _kinsoku_break(cur, ch):
    """Split the current line so the next one does not open with `ch`.

    Returns ``(head, tail)``: `head` is the line to emit, `tail` moves down to
    join `ch` on the next line. Retreating (rather than pushing `ch` up) keeps
    every line within the measured width. The retreat is capped at three
    characters and always leaves one behind, so it cannot loop or empty a line.
    """
    if ch not in _KINSOKU_NO_START or len(cur) < 2:
        return cur, ""
    head, tail = cur[:-1], cur[-1]
    while tail[0] in _KINSOKU_NO_START and len(head) > 1 and len(tail) < 3:
        head, tail = head[:-1], head[-1] + tail
    return head, tail


def word_wrap(draw, text, font, max_w):
    """Wrap `text` to `max_w`.

    Space-delimited scripts wrap on spaces. A token in a space-less script
    (Chinese, Japanese, Thai) is wrapped between characters instead — without
    this, a Japanese descriptor is a single line that runs off both edges.
    A too-long Latin word is NOT broken mid-word (that would need real
    hyphenation); it is left over-wide so the overflow check can report it.
    """
    lines, cur = [], ""
    for word in text.split():
        candidate = f"{cur} {word}".strip()
        if draw.textlength(candidate, font=font) <= max_w:
            cur = candidate
            continue
        if cur:
            lines.append(cur)
            cur = ""
        if draw.textlength(word, font=font) <= max_w:
            cur = word
            continue
        if detect_script(word) not in _NO_SPACE_SCRIPTS:
            lines.append(word)      # reported by _overflow_reasons()
            continue
        for ch in word:
            if not cur or draw.textlength(cur + ch, font=font) <= max_w:
                cur += ch
                continue
            head, tail = _kinsoku_break(cur, ch)
            lines.append(head)
            cur = tail + ch
    if cur:
        lines.append(cur)
    return lines


def _measure(lines, font):
    """Height the given lines occupy when drawn by draw_lines()."""
    dummy = ImageDraw.Draw(Image.new("RGBA", (1, 1)))
    total = 0
    for line in lines:
        bbox = dummy.textbbox((0, 0), line, font=font)
        total += (bbox[3] - bbox[1]) + DESC_LINE_GAP
    return total


def fit_font(text, max_w, size_max, size_min, font_path, max_lines):
    """Largest size at which `text` wraps to `max_lines` lines within `max_w`.

    Returns ``(font, lines)``. If even `size_min` cannot satisfy the
    constraints, the min-size result is returned anyway — the caller decides
    what to do about it.
    """
    dummy = ImageDraw.Draw(Image.new("RGBA", (1, 1)))
    for size in range(size_max, size_min - 1, -4):
        f = ImageFont.truetype(font_path, size)
        lines = word_wrap(dummy, text, f, max_w)
        if len(lines) <= max_lines and all(
            dummy.textlength(line, font=f) <= max_w for line in lines
        ):
            return f, lines
    f = ImageFont.truetype(font_path, size_min)
    return f, word_wrap(dummy, text, f, max_w)


def fit_block(verb, desc, font_path):
    """Fit both headline lines horizontally, then shrink until they fit
    vertically between the text top and the device.

    Returns ``(verb_font, verb_lines, desc_font, desc_lines, block_h)``.
    """
    available = DEVICE_Y - MIN_TEXT_DEVICE_GAP - TEXT_TOP
    verb_size, desc_size = VERB_SIZE_MAX, DESC_SIZE_MAX

    while True:
        verb_font, verb_lines = fit_font(
            verb, MAX_VERB_W, verb_size, VERB_SIZE_MIN, font_path,
            MAX_VERB_LINES)
        desc_font, desc_lines = fit_font(
            desc, MAX_TEXT_W, desc_size, DESC_SIZE_MIN, font_path,
            MAX_DESC_LINES)
        block_h = _measure(verb_lines, verb_font) + VERB_DESC_GAP + \
            _measure(desc_lines, desc_font)
        if block_h <= available:
            break
        # Shrink the descriptor first — the verb is the ASO hook.
        if desc_size > DESC_SIZE_MIN:
            desc_size = max(DESC_SIZE_MIN, desc_size - 4)
        elif verb_size > VERB_SIZE_MIN:
            verb_size = max(VERB_SIZE_MIN, verb_size - 4)
        else:
            break

    return verb_font, verb_lines, desc_font, desc_lines, block_h


def _overflow_reasons(verb_lines, verb_font, desc_lines, desc_font, block_h):
    """Describe every way this headline still does not fit. Empty == fine."""
    dummy = ImageDraw.Draw(Image.new("RGBA", (1, 1)))
    reasons = []
    for label, lines, font, max_w, max_lines in (
        ("verb", verb_lines, verb_font, MAX_VERB_W, MAX_VERB_LINES),
        ("descriptor", desc_lines, desc_font, MAX_TEXT_W, MAX_DESC_LINES),
    ):
        widest = max((dummy.textlength(l, font=font) for l in lines), default=0)
        if widest > max_w:
            reasons.append(
                f"the {label} is {int(widest)}px wide at its smallest size, "
                f"over the {max_w}px safe area")
        if len(lines) > max_lines:
            reasons.append(
                f"the {label} needs {len(lines)} lines (max {max_lines})")
    available = DEVICE_Y - MIN_TEXT_DEVICE_GAP - TEXT_TOP
    if block_h > available:
        reasons.append(
            f"the headline block is {block_h}px tall, over the {available}px "
            f"between the text top and the device")
    return reasons


def draw_lines(draw, y, lines, font):
    """Draw pre-wrapped lines centred horizontally, returning the new y."""
    for line in lines:
        bbox = draw.textbbox((0, 0), line, font=font)
        h = bbox[3] - bbox[1]
        # Use anchor="mt" (middle-top) for pixel-perfect horizontal centering
        # Adjust y by bbox[1] offset so text top aligns with intended position
        draw.text((CANVAS_W // 2, y - bbox[1]), line, fill="white", font=font, anchor="mt")
        y += h + DESC_LINE_GAP
    return y


def compose(bg_hex, verb, desc, screenshot_path, output_path, font=None,
            strict=False):
    bg = hex_to_rgb(bg_hex)
    font_path, script, _ = pick_font(f"{verb}{desc}".upper(), font)
    check_rtl_support(script)

    # ── 1. Canvas ───────────────────────────────────────────────────
    canvas = Image.new("RGBA", (CANVAS_W, CANVAS_H), (*bg, 255))
    draw = ImageDraw.Draw(canvas)

    # ── 2. Fit both headline lines, then verify the block actually fits ─
    verb_font, verb_lines, desc_font, desc_lines, block_h = fit_block(
        verb.upper(), desc.upper(), font_path)
    reasons = _overflow_reasons(verb_lines, verb_font, desc_lines, desc_font,
                                block_h)
    if reasons:
        detail = "\n".join(f"  - {r}" for r in reasons)
        message = (
            f"HEADLINE DOES NOT FIT: '{verb} / {desc}'\n{detail}\n"
            f"  Shorten the headline for this locale (or split the descriptor "
            f"into fewer words) — a clipped scaffold must not be sent to the "
            f"image API."
        )
        if strict:
            raise SystemExit(f"✗ {message}")
        print(f"⚠ {message}", file=sys.stderr)

    # Device at fixed Y; text starts at fixed position
    device_y = DEVICE_Y

    # Draw text at centered position
    y = TEXT_TOP
    y = draw_lines(draw, y, verb_lines, verb_font)
    y += VERB_DESC_GAP
    draw_lines(draw, y, desc_lines, desc_font)
    device_x = (CANVAS_W - DEVICE_W) // 2
    screen_x = device_x + BEZEL
    screen_y = device_y + BEZEL

    # ── 4. Screenshot into screen area ──────────────────────────────
    shot = Image.open(screenshot_path).convert("RGBA")

    # Scale to fill screen width
    scale = SCREEN_W / shot.width
    sc_w = SCREEN_W
    sc_h = int(shot.height * scale)
    shot = shot.resize((sc_w, sc_h), Image.LANCZOS)

    # Screen extends to bottom of canvas + overflow
    screen_h = CANVAS_H - screen_y + 500

    # Screen mask (rounded rect)
    scr_mask = Image.new("L", canvas.size, 0)
    ImageDraw.Draw(scr_mask).rounded_rectangle(
        [screen_x, screen_y, screen_x + SCREEN_W, screen_y + screen_h],
        radius=SCREEN_CORNER_R,
        fill=255,
    )

    # Black screen bg + screenshot on top
    scr_layer = Image.new("RGBA", canvas.size, (0, 0, 0, 0))
    ImageDraw.Draw(scr_layer).rounded_rectangle(
        [screen_x, screen_y, screen_x + SCREEN_W, screen_y + screen_h],
        radius=SCREEN_CORNER_R,
        fill=(0, 0, 0, 255),
    )
    scr_layer.paste(shot, (screen_x, screen_y))
    scr_layer.putalpha(scr_mask)

    canvas = Image.alpha_composite(canvas, scr_layer)

    # ── 6. Device frame template ───────────────────────────────────
    frame_template = Image.open(FRAME_PATH).convert("RGBA")

    # Place frame template onto canvas-sized layer at calculated position
    frame_layer = Image.new("RGBA", canvas.size, (0, 0, 0, 0))
    frame_layer.paste(frame_template, (device_x, device_y))
    canvas = Image.alpha_composite(canvas, frame_layer)

    # ── 7. Save ────────────────────────────────────────────────────
    canvas.convert("RGB").save(output_path, "PNG")
    print(f"✓ {output_path} ({CANVAS_W}×{CANVAS_H})")


def main():
    p = argparse.ArgumentParser(description="Compose App Store screenshot")
    p.add_argument("--bg", help="Background hex colour (#E31837)")
    p.add_argument("--font", default=None,
                   help="Font filename or full path. Overrides $ASO_FONT. "
                        "Auto-detected per platform when omitted: SF Pro Display "
                        "Black (macOS), Noto Sans Black (Linux), Arial Bold "
                        "(Windows)")
    p.add_argument("--verb", required=True, help="Action verb (TRACK)")
    p.add_argument("--desc", required=True, help="Benefit descriptor (TRADING CARD PRICES)")
    p.add_argument("--screenshot", help="Simulator screenshot path")
    p.add_argument("--output", help="Output file path")
    p.add_argument("--check", action="store_true",
                   help="Report the font/script/RTL support for this headline "
                        "and exit without composing anything")
    p.add_argument("--strict", action="store_true",
                   help="Fail (exit 1) instead of warning when the headline "
                        "does not fit the safe area — use this in any pipeline "
                        "that feeds a paid image API")
    args = p.parse_args()

    if args.check:
        font_path, script, substituted = pick_font(
            f"{args.verb}{args.desc}".upper(), args.font)
        rtl_ok = check_rtl_support(script)
        print(f"font:        {font_path}")
        print(f"script:      {script}")
        print(f"substituted: {substituted}")
        print(f"raqm:        {features.check('raqm')}")
        print(f"rtl-ready:   {rtl_ok}")
        return

    missing = [f"--{n}" for n in ("bg", "screenshot", "output")
               if getattr(args, n) is None]
    if missing:
        p.error(f"the following arguments are required: {', '.join(missing)}")

    compose(args.bg, args.verb, args.desc, args.screenshot, args.output,
            font=args.font, strict=args.strict)


if __name__ == "__main__":
    main()
