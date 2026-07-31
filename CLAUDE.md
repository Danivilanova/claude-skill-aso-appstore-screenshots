# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## What This Is

A Claude Code skill (`aso-appstore-screenshots`) that guides users through creating high-converting App Store screenshots, in every App Store Connect locale they ship. It is invoked via the `/aso-appstore-screenshots` slash command from within a user's app project.

## Architecture

Six files + one asset make up the skill:

- **SKILL.md** — The skill prompt. Defines a multi-phase workflow: RECALL → Benefit Discovery → Localization → Screenshot Pairing → Generation → Showcase, plus a **Conversion Design Playbook** reference section (12 principles, narrative arcs, HERO/FEATURE/SOCIAL slide templates, anti-patterns, thumbnail test) distilled from 8 high-converting reference sets and wired into those phases. Uses Claude Code's memory system to persist state across conversations (keyed by `(locale, benefit)` from the Localization phase onward) so users can resume mid-workflow. Generation first creates a deterministic scaffold via compose.py, then enhances it through generate_ai.py, then resizes with resize.py.
- **compose.py** — A standalone Python compositing script (Pillow-based) that deterministically renders App Store screenshots. Takes a background hex colour, action verb, benefit descriptor, and simulator screenshot path, then produces a pixel-perfect 1290×2796 PNG with headline text, device frame template, and the screenshot composited inside. Both headline lines auto-size and wrap inside the centre 75% safe area (`SAFE_W_FRACTION`), with character-level wrapping for space-less scripts; `--strict` makes it exit non-zero rather than write a clipped scaffold. Resolves fonts per platform, honours `--font` / `$ASO_FONT`, substitutes a script-appropriate font when the chosen one lacks glyphs, and warns when RTL text is rendered without libraqm.
- **generate_ai.py** — AI enhancement via the OpenRouter Image API (`POST https://openrouter.ai/api/v1/images`). Takes a prompt and up to 16 reference images (scaffold first, then style templates), inlines them as base64 data URLs in `input_references`, and writes the returned images. Defaults to `openai/gpt-image-2`; `--dry-run` prints the payload without calling the API. Standard library only (urllib, 600s timeout), so it needs no pip install and never breaks the workflow half-way with a missing module.
- **resize.py** — Cross-platform crop and resize script (Pillow-based). Crops to the target aspect ratio (center-crop, top edge preserved) then resizes to exact pixel dimensions, optionally changing the extension with `--ext`. Replaces the macOS-only `sips` commands. Works on macOS, Linux, and Windows.
- **generate_frame.py** — Generates the device frame template PNG (`assets/device_frame.png`). Run once to create or update the template. The template is a 1290×2796 RGBA PNG with a black iPhone body, transparent screen cutout, Dynamic Island, and side buttons.
- **showcase.py** — Generates a showcase image showing up to 3 final screenshots (.jpg or .png) side-by-side with an optional GitHub link at the bottom. Run once per locale, after that locale's set is approved. The caption font ignores `$ASO_FONT` on purpose — that variable is a per-locale headline font and has no business setting a Latin URL.
- **assets/device_frame.png** — Pre-rendered iPhone device frame template used by compose.py. Using a template instead of drawing the frame at compose time ensures pixel-perfect consistency across all generated screenshots.

Every script carries PEP 723 inline metadata, so `uv run <script>` provisions its dependencies. With plain `python3` the only install needed is `Pillow`; generate_ai.py is stdlib-only.

## Environment variables

| Variable | Default | Used by |
|----------|---------|---------|
| `OPENROUTER_API_KEY` | — (required) | generate_ai.py |
| `ASO_IMAGE_MODEL` | `openai/gpt-image-2` | generate_ai.py |
| `ASO_IMAGE_QUALITY` | `high` | generate_ai.py |
| `ASO_HTTP_REFERER`, `ASO_APP_TITLE` | — | generate_ai.py (OpenRouter attribution headers) |
| `ASO_FONT` | platform default | compose.py (headline only — showcase.py ignores it) |

## Running compose.py

```bash
# Requires: pip install Pillow (or: uv run compose.py …)

python3 compose.py --strict \
  --bg "#E31837" \
  --verb "TRACK" \
  --desc "TRADING CARD PRICES" \
  --screenshot path/to/simulator.png \
  --output output.png \
  --font "Inter-Black.otf"   # optional; also honours $ASO_FONT

# --strict: fail instead of writing a scaffold whose headline does not fit

# Report font/script/RTL support for a headline without composing anything
python3 compose.py --check --verb "追跡" --desc "カード価格"
```

## Running generate_ai.py

```bash
export OPENROUTER_API_KEY=sk-or-...

python3 generate_ai.py \
  --prompt-file prompt.txt \
  --input screenshots/en-US/01-benefit/scaffold.png \
  --input screenshots/final/en-US/01-first-benefit.jpg \
  --output-dir screenshots/en-US/01-benefit \
  --n 3

# Inspect the request without spending anything
python3 generate_ai.py --prompt "test" --input scaffold.png --dry-run
```

## Running resize.py

```bash
# Requires: pip install Pillow

# Default: iPhone 6.7" (1290×2796); PNG intermediates out as .jpg
python3 resize.py --ext jpg screenshots/en-US/01-benefit/v*.png

# Custom dimensions (e.g. iPhone 6.5")
python3 resize.py --width 1242 --height 2688 screenshots/en-US/01-benefit/v*.png
```

Each input file gets a `-resized` sibling (e.g. `v1.png` → `v1-resized.jpg`). Crops to the target aspect ratio (center-crop, top edge preserved) then resizes to exact dimensions.

## Key Design Decisions

- **Two-stage generation**: compose.py creates a deterministic scaffold first (text + frame + screenshot), then the image model enhances it. This avoids the inconsistencies of generating from scratch — and it is what makes localization safe, because the headline is drawn by Pillow rather than spelled by the model.
- **OpenRouter, not an MCP server**: the AI step is a plain HTTPS call from generate_ai.py, so the skill depends on one API key instead of a third-party npm MCP server. The model is swappable via `ASO_IMAGE_MODEL`; `google/*` image models only accept `n=1`, so generate_ai.py loops the request for them.
- **compose.py outputs exact App Store Connect dimensions** (1290×2796 for iPhone 6.7"). The AI step, however, generates at 9:16 — so resize.py afterwards is mandatory.
- **Locales, not languages**: everything downstream of the Localization phase is keyed on App Store Connect locale codes (`es-ES` ≠ `es-MX`), because each is a separate upload slot with its own copy. Output lives in `screenshots/[locale]/…` and `screenshots/final/[locale]/…`, and every locale shares the same pixel dimensions.
- **One style template per locale**: never feed another locale's approved screenshot as a style reference — the model reads the text in the reference and leaks the source language into the output.
- **Script coverage is a font problem, not a hard limit**: compose.py detects the headline's script, checks glyph coverage against the .notdef box, and substitutes a system font (Hiragino Sans / Noto Sans CJK, SF Arabic / Noto Naskh Arabic, SF Hebrew, Thonburi, …). RTL locales are the real caveat: Pillow shapes Arabic/Hebrew correctly only when built with libraqm, so compose.py warns and the skill asks the user before generating those locales.
- **Device frame is a template image** (`assets/device_frame.png`) — not drawn at compose time. Regenerate with `python3 generate_frame.py` if the frame design needs updating.
- **Headline text auto-sizes and is validated** — the verb shrinks 256→150px, the descriptor 124→80px, both wrap inside the centre 75% of the canvas (the width that survives the 9:16 crop), and space-less scripts (CJK, Thai) wrap between characters. If it still does not fit, compose.py reports exactly why: a warning by default, exit 1 under `--strict`, which is what SKILL.md uses so a clipped scaffold never reaches the paid API.
- **SKILL.md always generates 3 variants** for each benefit so the user can pick the best one — a single `generate_ai.py --n 3` call.
- **File extensions**: scaffolds and AI intermediates are `.png`; everything in `final/` is `.jpg` (resize.py's `--ext jpg` does the conversion).
- **The playbook drives the prompts, not just the prose**: the design guidance distilled from the reference sets is expressed as filled-in blocks inside the Stage 2 prompt templates (slide role, one accent word, one mandatory breakout, zoom region, gesture, swipe cue, background system, proof) — because only what reaches the prompt reaches the image. Two of those decisions (accent technique, background system) are chosen once per set and repeated identically.
- **Real proof only**: the skill asks the user which social proof exists and is under standing instructions never to invent or round up a rating, download count, award, press logo or review — an image model renders any number it is handed as though it were true. A variant that adds proof of its own is discarded, not accepted.
- **Where the playbook and the older rules disagreed**, the playbook won but the fallback is documented: backgrounds went from "solid colour only" to "one system for the whole set" (solid is still the default and what the scaffold emits, gradient families and panoramic artwork are allowed as systems), and the blanket ban on extra elements now permits one consistent personality system (mascot or domain props) while still banning generic clip-art and per-slide improvisation.
- **Memory is central to the workflow** — benefits, locales and their approved translations, screenshot assessments, pairings, brand colour, per-locale fonts, and generation state are all persisted so users can resume across conversations.
