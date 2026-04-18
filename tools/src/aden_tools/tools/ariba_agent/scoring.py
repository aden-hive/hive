from __future__ import annotations

import re
from typing import Dict


def _match(text: str, keywords: list[str]) -> bool:
    return any(re.search(rf"\b{re.escape(k)}\b", text) for k in keywords)


def score_opportunity(opp: Dict[str, object]) -> float:
    """
    Compute weighted Tech-Moat score.

    Returns:
        float: Confidence score [0, 1].
    """
    text = f"{opp.get('title','')} {opp.get('description','')}".lower()
    score = 0.0

    if _match(text, ["ai", "machine learning", "nlp", "computer vision"]):
        score += 0.3

    if _match(text, ["cloud", "saas", "paas", "api"]):
        score += 0.2

    if _match(text, ["robotics", "vision", "web3", "radar"]):
        score += 0.2

    if opp.get("budget") and float(opp["budget"]) > 50000:
        score += 0.1

    if _match(text, ["urgent", "immediate"]):
        score += 0.1

    if _match(text, ["enterprise", "scalable", "platform"]):
        score += 0.1

    return min(score, 1.0)
