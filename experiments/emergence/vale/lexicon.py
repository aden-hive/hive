"""Topic tags for signals: a keyword lexicon, cheap and inspectable."""

from __future__ import annotations

import re
from functools import lru_cache

LEXICON: dict[str, tuple[str, ...]] = {
    "water": ("water", "river", "brook", "hollowbrook", "stream", "well", "millrace", "ford", "drink", "drank", "spring"),
    "rust": ("rust", "red", "iron", "blood", "brine", "crimson", "wyrm", "redsilver"),
    "sickness": (
        "sick", "ill", "illness", "cough", "fever", "blight", "plague", "pox", "grey-lipped", "grey lips",
        "ague", "dying", "poison", "rot", "lame", "retch", "vomit", "disease", "ailing", "spit",
    ),
    "mine": ("mine", "miner", "shaft", "vein", "ore", "greyfang", "gallery", "tunnel", "digging", "deep door"),
    "money": ("coin", "silver", "debt", "tax", "price", "pay", "paid", "ledger", "gold", "tithe", "owe", "profit"),
    "law": ("lord", "thornkeep", "steward", "reeve", "petition", "decree", "law", "aldric", "osric", "court", "justice", "the keep"),
    "faith": ("saint", "wenna", "pray", "prayer", "chapel", "god", "sin", "holy", "bless", "priest", "prioress", "scripture", "heaven"),
    "omen": ("omen", "sign", "raven", "dream", "portent", "glow", "curse", "cursed", "judgment", "judgement", "warning"),
    "magic": ("witch", "hex", "spell", "charm", "herb", "herbs", "moonwort", "remedy", "potion", "gytha", "cunning", "tea", "salve"),
    "ancient": (
        "barrow", "stone", "stones", "king", "edric", "carving", "carved", "legend", "song", "verse",
        "old script", "serpent", "ancient", "rune", "snake",
    ),
    "wolves": ("wolf", "wolves", "pack", "howl", "howled", "tracks", "hunt"),
    "danger": ("danger", "attack", "afraid", "fear", "beware", "flee", "fire", "collapse", "quake", "shook", "kill", "scream"),
    "food": ("bread", "flour", "grain", "meal", "ale", "mutton", "game", "harvest", "hungry", "eat", "barley"),
    "trade": ("market", "buy", "sell", "trader", "goods", "cart", "fenford", "peddler", "barge", "cedric", "stall"),
    "stranger": ("stranger", "foreign", "traveler", "traveller", "fox", "outsider", "friar", "bagel", "tail"),
    "art": ("paint", "painting", "picture", "colour", "color", "canvas", "sketch"),
    "help": ("help", "please", "need", "come quick", "aid", "beg", "will you", "can you"),
    "children": ("child", "children", "baby", "boy", "girl", "babe", "pip", "son", "daughter"),
    "gathering": ("feast", "festival", "market day", "gather", "meeting", "moot", "together", "everyone"),
    "death": ("dead", "death", "died", "grave", "funeral", "corpse", "buried"),
    "weather": ("frost", "rain", "snow", "storm", "wind", "fog", "cold"),
}


@lru_cache(maxsize=None)
def _pattern(word: str) -> re.Pattern[str]:
    # Word-start boundary plus an optional plural, so "ore" doesn't match "before".
    return re.compile(r"\b" + re.escape(word) + r"(?:s|es)?\b", re.IGNORECASE)


def tags_for(text: str) -> list[str]:
    """Every topic whose keywords appear in `text`."""
    return [tag for tag, words in LEXICON.items() if any(_pattern(w).search(text) for w in words)]


def mentions(text: str, aliases: list[str]) -> bool:
    return any(_pattern(a).search(text) for a in aliases)
