"""Topic tags for signals: a story's keyword lexicon, cheap and inspectable.

A story pack lists its topics and the words that raise them (``story.toml``: ``[lexicon]``).
Latin words match as whole words, with an optional plural, so "ore" doesn't match "before";
words in scripts without spaces, such as Chinese, match anywhere in the text.
"""

from __future__ import annotations

import re
from functools import cache

Lexicon = tuple[tuple[str, tuple[re.Pattern[str], ...]], ...]


@cache
def _pattern(word: str) -> re.Pattern[str]:
    if word.isascii():
        return re.compile(r"\b" + re.escape(word) + r"(?:s|es)?\b", re.IGNORECASE)
    return re.compile(re.escape(word), re.IGNORECASE)


def compile_lexicon(table: dict[str, list[str]]) -> Lexicon:
    return tuple((tag, tuple(_pattern(w) for w in words)) for tag, words in table.items())


def tags_for(text: str, lexicon: Lexicon) -> list[str]:
    """Every topic whose keywords appear in `text`."""
    return [tag for tag, patterns in lexicon if any(p.search(text) for p in patterns)]


def mentions(text: str, aliases: list[str]) -> bool:
    return any(_pattern(a).search(text) for a in aliases if a)
