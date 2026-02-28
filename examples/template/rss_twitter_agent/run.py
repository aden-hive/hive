#!/usr/bin/env python
"""Backward-compatible wrapper to run the v0.6 RSS template package."""

from __future__ import annotations

import asyncio
import json
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(REPO_ROOT / "core"))
sys.path.insert(0, str(REPO_ROOT / "examples" / "templates"))

from rss_twitter_agent.run import run_interactive  # noqa: E402


if __name__ == "__main__":
    result = asyncio.run(run_interactive())
    print(json.dumps(result, indent=2, default=str))
