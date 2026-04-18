from __future__ import annotations

import re
from typing import Dict, List


TECH_MOAT = {
    "intelligence": ["ai", "nlp", "machine learning", "natural language"],
    "infrastructure": ["cloud", "saas", "paas", "api"],
    "advanced": ["robotics", "computer vision", "web3", "radar", "media"],
}


def _match(text: str, keywords: List[str]) -> bool:
    return any(re.search(rf"\b{re.escape(k)}\b", text) for k in keywords)


def classify_tech_moat(text: str) -> Dict[str, bool]:
    text = text.lower()
    return {k: _match(text, v) for k, v in TECH_MOAT.items()}


def filter_opportunities(opps: List[Dict[str, object]]) -> List[Dict[str, object]]:
    filtered = []

    for opp in opps:
        desc = str(opp.get("description", "")).lower()
        if any(_match(desc, kws) for kws in TECH_MOAT.values()):
            filtered.append(opp)

    return filtered
