"""
tools/calibrate_voice.py
One-time voice calibration script. Fetches your recent LinkedIn posts via LinkdAPI
and generates a personal voice profile for the drafting node.

Usage:
    python tools/calibrate_voice.py

Requires LINKDAPI_KEY in .env. config.yaml must exist (run setup first).
Output: skills/outreach-rules/references/voice-profile.md
"""

import os
import re
import sys
from pathlib import Path

try:
    from dotenv import load_dotenv
    load_dotenv(Path(__file__).parent.parent / ".env")
except ImportError:
    pass

import requests

ROOT = Path(__file__).parent.parent
VOICE_PROFILE_PATH = ROOT / "skills" / "outreach-rules" / "references" / "voice-profile.md"
CONFIG_PATH = ROOT / "config.yaml"
LINKDAPI_BASE = "https://linkdapi.com/api/v1"


def _extract_username(raw: str) -> str:
    raw = raw.strip().rstrip("/")
    m = re.search(r"linkedin\.com/in/([^/?#\s]+)", raw)
    return m.group(1).rstrip("/") if m else raw


def _linkdapi_headers(api_key: str) -> dict:
    return {"X-linkdapi-apikey": api_key}


def _fetch_urn(username: str, api_key: str) -> str:
    url = f"{LINKDAPI_BASE}/username-to-urn"
    resp = requests.get(url, headers=_linkdapi_headers(api_key), params={"username": username}, timeout=20)
    resp.raise_for_status()
    data = resp.json()
    if not data.get("success"):
        raise RuntimeError(f"LinkdAPI error: {data}")
    urn = data.get("data", {}).get("urn") or data.get("urn")
    if not urn:
        raise RuntimeError(f"No URN returned for username '{username}'. Check that the profile is public.")
    return urn


def _fetch_posts(urn: str, api_key: str) -> list[dict]:
    url = f"{LINKDAPI_BASE}/posts/all"
    resp = requests.get(url, headers=_linkdapi_headers(api_key), params={"urn": urn}, timeout=30)
    resp.raise_for_status()
    data = resp.json()
    if not data.get("success"):
        raise RuntimeError(f"LinkdAPI error: {data}")
    inner = data.get("data", {})
    if isinstance(inner, list):
        return inner
    return inner.get("elements", inner.get("posts", inner.get("results", [])))


def _extract_post_texts(posts: list[dict]) -> list[str]:
    texts = []
    for post in posts:
        text = post.get("text", "") or ""
        text = text.strip()
        if text:
            texts.append(text)
    return texts


def _build_voice_profile(post_texts: list[str], n_total: int, model: str) -> str:
    from pipeline_v2.lib.llm_client import call_llm

    # Cap at 50 posts for token efficiency; use the full count in the header
    sample = post_texts[:50]
    posts_block = "\n\n---\n\n".join(sample)

    system = f"""You are a writing style analyst. Extract a precise, actionable voice profile from a set of LinkedIn posts.

Every rule must be actionable and specific — a concrete instruction a writer can apply immediately, like:
  "open with a verb, not a noun: 'noticed X' not 'X is a thing'"
NOT vague descriptors like "be direct", "authentic", "clear".

Analyze the posts and produce a voice profile in exactly this markdown format. Replace [N] with {n_total}. Replace every bracketed placeholder with real observations derived from the posts.

# Voice Profile

Extracted from [N] LinkedIn posts. Used by the drafting node when tone_matching is enabled.

## Opening observation style
- [specific actionable rule]
- [specific actionable rule]

## Sentence rhythm and structure
- [specific actionable rule]
- [specific actionable rule]

## How technical things are explained
- [specific actionable rule]

## Curiosity vs confidence signals
- [specific actionable rule]
- [specific actionable rule]

## Vocabulary patterns
- Words reached for: [comma-separated list of characteristic words or phrases]
- Words avoided: [comma-separated list]

## Phrasing for questions and soft asks
- [specific actionable rule]

## Tone signature
- [specific actionable rule]
- [specific actionable rule]"""

    user_content = f"Here are {n_total} LinkedIn posts. Analyze and extract the voice profile.\n\n{posts_block}"

    content, _, _ = call_llm(
        model=model,
        messages=[{"role": "user", "content": user_content}],
        system=system,
        max_tokens=2000,
    )
    return content


def _enable_tone_matching() -> bool:
    if not CONFIG_PATH.exists():
        return False
    text = CONFIG_PATH.read_text()
    if "tone_matching: false" in text:
        CONFIG_PATH.write_text(text.replace("tone_matching: false", "tone_matching: true"))
        return True
    if "tone_matching: true" in text:
        return True
    return False  # key absent — old config, user hasn't run setup with the new example


def main() -> None:
    answer = input("Calibrate the drafting voice to match your LinkedIn writing style? (y/n): ").strip().lower()
    if answer != "y":
        print("Skipped.")
        return

    linkdapi_key = os.environ.get("LINKDAPI_KEY")
    if not linkdapi_key:
        print("Error: LINKDAPI_KEY is not set in your .env.", file=sys.stderr)
        print("Add LINKDAPI_KEY=<your-key> to .env and re-run.", file=sys.stderr)
        sys.exit(1)

    raw = input("Your LinkedIn profile URL or username: ").strip()
    if not raw:
        print("No input provided. Exiting.", file=sys.stderr)
        sys.exit(1)

    username = _extract_username(raw)
    print(f"  Using username: {username}")

    if VOICE_PROFILE_PATH.exists():
        overwrite = input("Voice profile already exists. Overwrite? (y/n): ").strip().lower()
        if overwrite != "y":
            print("Skipped.")
            return

    if not CONFIG_PATH.exists():
        print("Error: config.yaml not found. Run setup first, then re-run calibrate_voice.py.", file=sys.stderr)
        sys.exit(1)

    try:
        from tools.config_loader import cfg
        model = cfg.models.utility
    except AttributeError as e:
        print(f"Error: {e}", file=sys.stderr)
        sys.exit(1)

    print("Fetching LinkedIn URN...")
    try:
        urn = _fetch_urn(username, linkdapi_key)
    except Exception as e:
        print(f"Error fetching URN: {e}", file=sys.stderr)
        sys.exit(1)

    print("Fetching LinkedIn posts...")
    try:
        posts = _fetch_posts(urn, linkdapi_key)
    except Exception as e:
        print(f"Error fetching posts: {e}", file=sys.stderr)
        sys.exit(1)

    post_texts = _extract_post_texts(posts)
    n = len(post_texts)
    print(f"  Found {n} posts.")

    if n < 10:
        warn = input(
            f"Only {n} posts found — voice profile may be less accurate. Continue? (y/n): "
        ).strip().lower()
        if warn != "y":
            print("Aborted.")
            return

    print("Generating voice profile...")
    try:
        voice_profile = _build_voice_profile(post_texts, n, model)
    except Exception as e:
        print(f"Error generating voice profile: {e}", file=sys.stderr)
        sys.exit(1)

    VOICE_PROFILE_PATH.parent.mkdir(parents=True, exist_ok=True)
    VOICE_PROFILE_PATH.write_text(voice_profile.strip() + "\n")
    print(f"✓ Voice profile written to {VOICE_PROFILE_PATH.relative_to(ROOT)}")

    if _enable_tone_matching():
        print("✓ tone_matching enabled in config.yaml")
    else:
        print("Run setup first, then re-run calibrate_voice.py to enable tone_matching.")


if __name__ == "__main__":
    main()
