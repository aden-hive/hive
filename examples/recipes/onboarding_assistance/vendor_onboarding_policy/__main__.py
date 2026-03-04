from __future__ import annotations
import argparse
import json
from pathlib import Path
from typing import Any, Dict, Optional

from .agent import run


def _load_json(path: str) -> Dict[str, Any]:
    return json.loads(Path(path).read_text(encoding="utf-8"))


def main() -> None:
    parser = argparse.ArgumentParser(description="Run vendor_onboarding_policy agent (deterministic MVP).")
    parser.add_argument("--input", required=True, help="Path to input JSON file")
    parser.add_argument("--human", required=False, help="Optional path to human decision JSON")
    args = parser.parse_args()

    inp = _load_json(args.input)
    human: Optional[Dict[str, Any]] = _load_json(args.human) if args.human else None

    result = run(inp, human=human)
    print(json.dumps(result, indent=2, ensure_ascii=False))


if __name__ == "__main__":
    main()
