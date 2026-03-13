#!/usr/bin/env python
"""Quick flow test for RSS-to-Twitter interactive runner."""

from __future__ import annotations

import asyncio
import json

from .run import run_interactive


async def test_full_flow() -> None:
    result = await run_interactive(max_articles=1)
    print(json.dumps(result, indent=2, default=str))


if __name__ == "__main__":
    asyncio.run(test_full_flow())
