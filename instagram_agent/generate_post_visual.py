"""Generate an Instagram post visual using Google's Gemini 2.5 Flash Image (Nano Banana).

Usage:
    export GEMINI_API_KEY=...
    python generate_post_visual.py "A minimalist flat-lay of a matcha latte on linen"

Outputs a PNG to ./output/ sized for Instagram feed posts.
"""

from __future__ import annotations

import base64
import os
import sys
from datetime import datetime
from pathlib import Path

import requests

MODEL = "gemini-2.5-flash-image"
ENDPOINT = (
    f"https://generativelanguage.googleapis.com/v1beta/models/{MODEL}:generateContent"
)
OUTPUT_DIR = Path(__file__).parent / "output"


def generate_image(prompt: str, api_key: str) -> bytes:
    """Call Gemini and return the raw image bytes."""
    response = requests.post(
        ENDPOINT,
        params={"key": api_key},
        headers={"Content-Type": "application/json"},
        json={
            "contents": [{"parts": [{"text": prompt}]}],
            "generationConfig": {"responseModalities": ["IMAGE"]},
        },
        timeout=120,
    )
    response.raise_for_status()
    data = response.json()

    for part in data["candidates"][0]["content"]["parts"]:
        inline = part.get("inlineData") or part.get("inline_data")
        if inline and inline.get("data"):
            return base64.b64decode(inline["data"])

    raise RuntimeError(f"No image in response: {data}")


def main() -> int:
    api_key = os.environ.get("GEMINI_API_KEY") or os.environ.get("GOOGLE_API_KEY")
    if not api_key:
        print("ERROR: set GEMINI_API_KEY in the environment.", file=sys.stderr)
        return 1

    prompt = " ".join(sys.argv[1:]) or (
        "A bright, airy flat-lay Instagram post: iced matcha latte in a clear glass "
        "on a cream linen background, fresh mint leaves, soft morning light, "
        "minimalist composition, vertical 4:5 framing, editorial food photography."
    )

    OUTPUT_DIR.mkdir(exist_ok=True)
    stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    out_path = OUTPUT_DIR / f"post-{stamp}.png"

    print(f"Prompt: {prompt}")
    print(f"Calling {MODEL}...")
    image_bytes = generate_image(prompt, api_key)
    out_path.write_bytes(image_bytes)
    print(f"Saved: {out_path} ({len(image_bytes):,} bytes)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
