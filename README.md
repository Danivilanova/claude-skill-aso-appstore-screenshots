# ASO App Store Screenshots

A Claude Code skill that generates high-converting App Store screenshots for your iOS app — in every locale you ship. It analyzes your codebase, identifies the core benefits that drive downloads, and creates professional screenshot images using AI.

## What It Does

1. **Benefit Discovery** — Analyzes your app's codebase to identify the 3–5 core benefits that drive downloads, then collaborates with you to refine and confirm them
2. **Localization** — Resolves the App Store Connect locales you ship (`en-US`, `es-ES`, `ja`, …), translates each headline, and back-translates it so you can confirm the meaning before anything is generated
3. **Screenshot Pairing** — Reviews your simulator screenshots, rates them (Great / Usable / Retake), and pairs each with the most relevant benefit
4. **Generation** — Creates polished App Store screenshots using a two-stage pipeline: deterministic scaffolding (`compose.py`) + AI enhancement (GPT Image 2 via OpenRouter)
5. **Showcase** — Generates a side-by-side preview image per locale

Progress is saved to Claude Code's memory system after each phase, so you can resume across conversations without starting over.

### Runs itself as an orchestrator

The model running the skill acts as an orchestrator: it keeps the conversation, the benefit decisions, the design choices and the image prompts, and pushes the bounded work to subagents on the cheapest model that can do it — haiku for mechanical batches (scaffolding, resizing, showcases), sonnet for codebase research and translation, opus for independent design review of the generated slides. Codebase research and per-locale work run in parallel.

This is defined entirely inside `SKILL.md` using the generic Claude Code agent mechanism — no custom agent definitions and no configuration to install. If the environment has no agent tool at all, the skill runs every step inline in the same order and produces the same result.

### Built on a conversion playbook, not on taste

The skill carries a **Conversion Design Playbook** distilled from a visual analysis of 8 high-converting App Store screenshot sets across different categories. It shapes the whole workflow, not just the wording: the set is structured as HERO → FEATURE (in the order a real user walks the app) → SOCIAL/OUTCOME; benefits are pushed toward quantified claims; every slide gets exactly one accented word, exactly one element broken out of the device frame, a zoom to the moment that matters and a swipe cue pulling the eye to the next slide; and the finished set has to survive a thumbnail test at ~150px wide.

It also asks which social proof you genuinely have — rating and review count, downloads, press, awards, a defensible niche claim — and **never invents any of it**. Whatever you don't have is simply left off the slide.

---

## Installation

### 1. Install the skill

There is no `claude install-skill` command — skills are installed by putting a folder into `~/.claude/skills/`. Clone straight into place:

```bash
git clone https://github.com/adamlyttleapps/claude-skill-aso-appstore-screenshots.git \
  ~/.claude/skills/aso-appstore-screenshots
```

To update it later:

```bash
git -C ~/.claude/skills/aso-appstore-screenshots pull
```

### 2. Install Python dependencies

```bash
pip install Pillow
```

Pillow is the only third-party dependency, and only the image scripts need it — `generate_ai.py` is standard library only. You can also skip this step and run everything with [`uv`](https://docs.astral.sh/uv/): the scripts declare their dependencies inline (PEP 723), so `uv run compose.py …` handles it.

### 3. Font requirement

The skill auto-detects a suitable headline font per platform:

| Platform | Default font | Install |
|----------|-------------|---------|
| **macOS** | SF Pro Display Black | [Apple Developer Fonts](https://developer.apple.com/fonts/) → `/Library/Fonts/SF-Pro-Display-Black.otf` |
| **Linux** | Noto Sans Black | `sudo apt install fonts-noto-core` (usually pre-installed) |
| **Windows** | Arial Bold | Pre-installed |

To use a custom font, pass `--font` to `compose.py` with either a filename (searched in system font dirs) or a full path:

```bash
# By filename (searched in platform font directories)
python3 compose.py --font "Inter-Black.otf" ...

# By full path
python3 compose.py --font "/path/to/MyFont-Black.ttf" ...
```

The `ASO_FONT` environment variable does the same thing without touching the command line — handy for setting a per-locale font in CI or a shell profile. Precedence is `--font` → `$ASO_FONT` → the platform default:

```bash
export ASO_FONT=/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf
```

If the chosen font has no glyphs for a locale's script, compose.py substitutes a script-appropriate system font automatically and says so. Check what it would use for a given headline without generating anything:

```bash
python3 compose.py --check --verb "追跡" --desc "カード価格"
```

### 4. Set up an OpenRouter API key (required for AI enhancement)

The generation phase calls the [OpenRouter Image API](https://openrouter.ai) directly from `generate_ai.py` — there is no MCP server to install.

Create a key at [openrouter.ai/keys](https://openrouter.ai/keys) and export it (add it to your shell profile so it persists):

```bash
export OPENROUTER_API_KEY=sk-or-...
```

Optional environment variables:

| Variable | Default | Purpose |
|----------|---------|---------|
| `OPENROUTER_API_KEY` | — | **Required.** Your OpenRouter key. |
| `ASO_IMAGE_MODEL` | `openai/gpt-image-2` | Image model. Alternatives: `google/gemini-3.1-flash-image` ("Nano Banana 2"), `google/gemini-3-pro-image`. |
| `ASO_IMAGE_QUALITY` | `high` | Quality passed to the model. |
| `ASO_FONT` | platform default | Headline font path — used for locales whose script the default font can't render. |
| `ASO_HTTP_REFERER` / `ASO_APP_TITLE` | — | Optional OpenRouter attribution headers. |

**Rough cost:** a set of 5-10 screenshots (3 variants each) runs about **$1-2** with `gpt-image-2` at high quality, or about **$0.35-0.80** with Nano Banana 2 - multiplied by the number of locales you generate. `generate_ai.py --dry-run` prints the request payload without spending anything.

---

## Usage

Open a Claude Code session inside your app's project directory and run:

```
/aso-appstore-screenshots
```

The skill will guide you through each phase interactively. If you've run it before, it will check memory first and offer to resume from where you left off.

---

## How It Works

### Scaffold → Enhance Pipeline

Rather than generating screenshots from scratch (which produces inconsistent results), the skill uses a two-stage approach:

1. **`compose.py`** creates a deterministic scaffold with exact text positioning, device frame placement, and your simulator screenshot composited inside — ensuring consistent layout across all screenshots
2. **`generate_ai.py`** sends that scaffold to the image model through OpenRouter — adding a photorealistic device frame, breakout elements, and visual polish
3. **`resize.py`** crops the 9:16 result down to Apple's exact pixel dimensions

This separation means layout is always predictable and repeatable, while the AI handles the creative enhancement. Because the headline is drawn by Pillow and not by the model, translated text is never mangled or re-spelled.

### Localization

The skill works in **App Store Connect locale codes**, not bare language codes — `es-ES` and `es-MX` are different upload slots with different copy, and it will ask which ones you actually ship. Each locale gets its own working folder, its own style template (so the model can't leak English words into a Spanish set), and is generated one at a time. Every locale uses the same pixel dimensions; only the text changes.

Scripts are handled by font substitution: compose.py detects the headline's script and swaps in a system font that covers it (Hiragino Sans / Noto Sans CJK for `ja`, `ko`, `zh-Hans`, `zh-Hant`; SF Arabic / Noto Naskh Arabic for `ar-SA`; SF Hebrew / Noto Sans Hebrew for `he`; and so on). You can always override with `ASO_FONT` or `--font`.

**RTL caveat, honestly:** Arabic and Hebrew need Pillow built with **libraqm** to be shaped and ordered correctly. Without it, letters render isolated and in reverse visual order. Run `compose.py --check --verb "…" --desc "…"` to see whether your Pillow has raqm; the skill warns and asks before generating an RTL locale on a build that doesn't.

### Output

Screenshots are saved to a `screenshots/` directory in your project root, organised by locale:

```
screenshots/
  en-US/                        ← working files for the base locale
    01-benefit-slug/
      scaffold.png              ← deterministic compose.py output
      prompt.txt                ← the enhancement prompt used
      v1.png, v2.png, v3.png    ← AI-enhanced variants (9:16 intermediates)
      v1-resized.jpg, ...       ← cropped to exact App Store dimensions
    02-benefit-slug/
      ...
  es-ES/                        ← same structure, Spanish headlines
    ...
  final/                        ← approved screenshots, ready to upload
    en-US/
      01-benefit-slug.jpg
      02-benefit-slug.jpg
    es-ES/
      01-benefit-slug.jpg
  showcase-en-US.png            ← one side-by-side preview per locale
  showcase-es-ES.png
```

The `final/[locale]/` folders are the only ones you need to care about — each contains one approved screenshot per benefit at exact Apple dimensions (default: 1290×2796px for iPhone 6.7") and maps 1:1 to an App Store Connect locale slot. Intermediates are PNG; everything in `final/` is `.jpg`.

---

## Files

| File | Purpose |
|---|---|
| `SKILL.md` | The skill prompt — defines the multi-phase workflow |
| `compose.py` | Deterministic scaffold generator (Pillow-based), with per-script font resolution |
| `generate_ai.py` | AI enhancement via the OpenRouter Image API (GPT Image 2 by default) |
| `resize.py` | Cross-platform crop and resize to exact store dimensions (Pillow-based) |
| `generate_frame.py` | Generates the device frame template |
| `showcase.py` | Generates the side-by-side showcase image |
| `assets/device_frame.png` | Pre-rendered iPhone device frame template |

Every script carries [PEP 723](https://peps.python.org/pep-0723/) inline metadata, so `uv run compose.py …` provisions its dependencies on its own. With plain `python3`, the only thing to install is Pillow (`pip install Pillow`) — `generate_ai.py` uses the standard library alone, so it runs anywhere.

---

## License

MIT
