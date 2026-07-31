#!/usr/bin/env python3
# /// script
# requires-python = ">=3.9"
# dependencies = []
# ///
"""
AI enhancement for App Store screenshot scaffolds, via the OpenRouter Image API.

Sends a scaffold (and optionally a style-reference image) plus a prompt to an
image model — GPT Image 2 by default — and writes the returned images to disk.

Standard library only, so `python3 generate_ai.py` works on any machine with
Python 3.9+ — no pip install, no virtualenv.

  export OPENROUTER_API_KEY=sk-or-...

  python3 generate_ai.py \
    --prompt-file prompt.txt \
    --input screenshots/en-US/01-track-prices/scaffold.png \
    --output-dir screenshots/en-US/01-track-prices \
    --n 3

Environment variables:
  OPENROUTER_API_KEY   required — get one at https://openrouter.ai/keys
  ASO_IMAGE_MODEL      default model (falls back to "openai/gpt-image-2")
  ASO_IMAGE_QUALITY    default quality (falls back to "high")
  ASO_HTTP_REFERER     optional, sent as HTTP-Referer (OpenRouter attribution)
  ASO_APP_TITLE        optional, sent as X-Title (OpenRouter attribution)
"""

import argparse
import base64
import json
import mimetypes
import os
import sys
import urllib.error
import urllib.request

API_URL = "https://openrouter.ai/api/v1/images"
DEFAULT_MODEL = "openai/gpt-image-2"
DEFAULT_QUALITY = "high"
MAX_INPUTS = 16
# High-quality image generation regularly runs past a minute; give it room.
TIMEOUT_S = 600


def data_url(path):
    """Read an image file and return it as a base64 data URL."""
    if not os.path.isfile(path):
        raise SystemExit(f"Input image not found: {path}")
    mime = mimetypes.guess_type(path)[0] or "image/png"
    with open(path, "rb") as fh:
        encoded = base64.b64encode(fh.read()).decode("ascii")
    return f"data:{mime};base64,{encoded}"


def build_payload(prompt, inputs, model, quality, aspect_ratio, output_format, n):
    payload = {
        "model": model,
        "prompt": prompt,
        "aspect_ratio": aspect_ratio,
        "quality": quality,
        "n": n,
        "output_format": output_format,
    }
    if inputs:
        payload["input_references"] = [
            {"type": "image_url", "image_url": {"url": data_url(p)}} for p in inputs
        ]
    return payload


def redacted(payload):
    """A copy of the payload with data URLs shortened, for printing."""
    clone = json.loads(json.dumps(payload))
    for ref in clone.get("input_references", []):
        url = ref["image_url"]["url"]
        head, _, tail = url.partition("base64,")
        ref["image_url"]["url"] = f"{head}base64,<{len(tail)} chars>"
    return clone


def post(payload, api_key):
    headers = {
        "Authorization": f"Bearer {api_key}",
        "Content-Type": "application/json",
    }
    referer = os.environ.get("ASO_HTTP_REFERER")
    title = os.environ.get("ASO_APP_TITLE")
    if referer:
        headers["HTTP-Referer"] = referer
    if title:
        headers["X-Title"] = title

    request = urllib.request.Request(
        API_URL,
        data=json.dumps(payload).encode("utf-8"),
        headers=headers,
        method="POST",
    )
    try:
        with urllib.request.urlopen(request, timeout=TIMEOUT_S) as response:
            body = response.read().decode("utf-8")
    except urllib.error.HTTPError as exc:
        detail = exc.read().decode("utf-8", "replace")
        raise SystemExit(
            f"OpenRouter returned HTTP {exc.code} {exc.reason}:\n{detail}")
    except urllib.error.URLError as exc:
        raise SystemExit(f"Could not reach {API_URL}: {exc.reason}")

    try:
        return json.loads(body)
    except json.JSONDecodeError:
        raise SystemExit(
            f"OpenRouter returned a non-JSON response:\n{body[:2000]}")


def save_images(body, output_dir, prefix, output_format, start_index):
    """Write every image in the response; return the saved paths."""
    os.makedirs(output_dir, exist_ok=True)
    saved = []
    for offset, item in enumerate(body.get("data", [])):
        b64 = item.get("b64_json")
        if not b64:
            print(f"⚠ response item {offset} has no b64_json, skipping",
                  file=sys.stderr)
            continue
        path = os.path.join(
            output_dir, f"{prefix}{start_index + offset}.{output_format}")
        with open(path, "wb") as fh:
            fh.write(base64.b64decode(b64))
        saved.append(path)
    return saved


def main():
    p = argparse.ArgumentParser(
        description="Enhance an App Store screenshot scaffold via OpenRouter")
    p.add_argument("--prompt", help="Enhancement prompt text")
    p.add_argument("--prompt-file", help="File containing the enhancement prompt")
    p.add_argument("--input", action="append", default=[], metavar="IMAGE",
                   help="Reference image (repeatable, max 16): the scaffold "
                        "first, then any style-template images")
    p.add_argument("--output-dir", default=".", help="Directory for the results")
    p.add_argument("--prefix", default="v", help="Output filename prefix (default: v)")
    p.add_argument("--start-index", type=int, default=1,
                   help="Number the first output file from this index (default: 1)")
    p.add_argument("--n", type=int, default=3, help="How many variants (default: 3)")
    p.add_argument("--model", default=os.environ.get("ASO_IMAGE_MODEL", DEFAULT_MODEL),
                   help=f"OpenRouter model id (default: $ASO_IMAGE_MODEL or {DEFAULT_MODEL})")
    p.add_argument("--quality",
                   default=os.environ.get("ASO_IMAGE_QUALITY", DEFAULT_QUALITY),
                   help=f"Image quality (default: $ASO_IMAGE_QUALITY or {DEFAULT_QUALITY})")
    p.add_argument("--aspect-ratio", default="9:16",
                   help="Generation aspect ratio (default: 9:16 — resize.py "
                        "crops it down to exact App Store dimensions)")
    p.add_argument("--output-format", default="png", choices=["png", "jpeg", "webp"],
                   help="Image format returned by the API (default: png)")
    p.add_argument("--dry-run", action="store_true",
                   help="Print the request payload and exit without calling the API")
    args = p.parse_args()

    if bool(args.prompt) == bool(args.prompt_file):
        p.error("provide exactly one of --prompt or --prompt-file")
    prompt = args.prompt
    if args.prompt_file:
        if not os.path.isfile(args.prompt_file):
            raise SystemExit(f"Prompt file not found: {args.prompt_file}")
        with open(args.prompt_file, encoding="utf-8") as fh:
            prompt = fh.read()

    if len(args.input) > MAX_INPUTS:
        raise SystemExit(
            f"Too many --input images ({len(args.input)}); the API accepts at "
            f"most {MAX_INPUTS}.")

    # Gemini image models only accept n=1 — loop the request instead.
    single_only = args.model.startswith("google/")
    per_call_n = 1 if single_only else args.n
    calls = args.n if single_only else 1

    payload = build_payload(prompt, args.input, args.model, args.quality,
                            args.aspect_ratio, args.output_format, per_call_n)

    if args.dry_run:
        if single_only and args.n > 1:
            print(f"# note: {args.model} only supports n=1 — this payload would "
                  f"be sent {args.n} times", file=sys.stderr)
        print(json.dumps(redacted(payload), indent=2, ensure_ascii=False))
        return

    api_key = os.environ.get("OPENROUTER_API_KEY")
    if not api_key:
        raise SystemExit(
            "OPENROUTER_API_KEY is not set.\n"
            "Create a key at https://openrouter.ai/keys, then:\n"
            "  export OPENROUTER_API_KEY=sk-or-...")

    saved, total_cost = [], 0.0
    for call in range(calls):
        body = post(payload, api_key)
        saved += save_images(body, args.output_dir, args.prefix,
                             args.output_format, args.start_index + len(saved))
        cost = (body.get("usage") or {}).get("cost")
        if isinstance(cost, (int, float)):
            total_cost += cost

    if not saved:
        raise SystemExit("The API returned no images.")
    for path in saved:
        print(f"✓ {path}")
    print(f"cost: ${total_cost:.4f} ({args.model}, {len(saved)} image(s))")


if __name__ == "__main__":
    main()
