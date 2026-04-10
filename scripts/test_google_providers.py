#!/usr/bin/env python3
"""Quick smoke test for Google Gemini providers."""

import sys
import os

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "core"))

from framework.llm.google import GoogleApiKeyProvider, GoogleGeminiCliProvider

MODELS = ["gemini-3-flash-preview", "gemini-3.1-pro-preview", "gemini-2.5-flash"]


def test_api_key(model: str) -> bool:
    print(f"\n--- GoogleApiKeyProvider: {model} ---")
    try:
        api_key = os.environ.get("GEMINI_API_KEY") or os.environ.get("GOOGLE_API_KEY")
        if not api_key:
            print("  SKIP: no API key found (set GEMINI_API_KEY or GOOGLE_API_KEY)")
            return False

        provider = GoogleApiKeyProvider(model=model, api_key=api_key)
        resp = provider.complete(
            messages=[{"role": "user", "content": "Say hello in one word."}],
            max_tokens=32,
        )
        text = resp.content.strip()
        print(f"  OK: {text!r}")
        return True
    except Exception as e:
        print(f"  FAIL: {e}")
        return False


def test_oauth(model: str) -> bool:
    print(f"\n--- GoogleGeminiCliProvider: {model} ---")
    try:
        provider = GoogleGeminiCliProvider(model=model)
        if not provider.has_credentials():
            print("  SKIP: no OAuth credentials found")
            return False

        resp = provider.complete(
            messages=[{"role": "user", "content": "Say hello in one word."}],
            max_tokens=32,
        )
        text = resp.content.strip()
        print(f"  OK: {text!r}")
        return True
    except Exception as e:
        print(f"  FAIL: {e}")
        return False


def main() -> int:
    results = {}
    for m in MODELS:
        results[f"apikey:{m}"] = test_api_key(m)
        results[f"oauth:{m}"] = test_oauth(m)

    print("\n=== Summary ===")
    for m, ok in results.items():
        status = "PASS" if ok else "FAIL"
        print(f"  {m}: {status}")

    return 0 if any(results.values()) else 1


if __name__ == "__main__":
    sys.exit(main())
