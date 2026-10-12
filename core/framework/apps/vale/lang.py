"""The engine's own words, per language: ``lang/<code>.toml``, with English behind every other table.

A story pack names its language (``story.toml``: ``[story] lang``); the world then speaks
through ``world.t("section.key", slot=value)``. Slots are ``{name}`` (or ``{name!r}``); any
other brace, such as the JSON a prompt shows a model, is left as it is.
"""

from __future__ import annotations

import re
import tomllib
from functools import cache
from pathlib import Path
from typing import Any

DIR = Path(__file__).resolve().parent / "lang"
_SLOT = re.compile(r"\{(\w+)(!r)?\}")


def _merge(base: dict, over: dict) -> dict:
    out = dict(base)
    for k, v in over.items():
        out[k] = _merge(base[k], v) if isinstance(v, dict) and isinstance(base.get(k), dict) else v
    return out


@cache
def table(lang: str) -> dict[str, Any]:
    en = tomllib.loads((DIR / "en.toml").read_text("utf-8"))
    path = DIR / f"{lang}.toml"
    if lang == "en" or not path.exists():
        return en
    return _merge(en, tomllib.loads(path.read_text("utf-8")))


def fill(template: str, **slots: Any) -> str:
    """Put the slots into a template; unknown slots and every other brace stay as written."""

    def put(m: re.Match) -> str:
        if m.group(1) not in slots:
            return m.group(0)
        value = slots[m.group(1)]
        return repr(value) if m.group(2) else str(value)

    return _SLOT.sub(put, template)


class Phrases:
    """``t("act.looked", name=..., thing=...)``; ``t.get("time.waves")`` for lists and tables."""

    def __init__(self, lang: str = "en") -> None:
        self.lang = lang
        self._table = table(lang)

    def get(self, key: str) -> Any:
        node: Any = self._table
        for part in key.split("."):
            node = node[part]
        return node

    def __call__(self, key: str, **slots: Any) -> str:
        return fill(self.get(key), **slots)
