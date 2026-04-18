
from typing import List, Dict

TECH_MOAT_KEYWORDS = {
    "intelligence": ["ai", "nlp", "machine learning", "computer vision"],
    "infrastructure": ["cloud", "saas", "distributed"],
    "advanced": ["robotics", "web3", "radar"]
}


def classify_tech_moat(text: str) -> Dict:
    text = text.lower()
    result = {}

    for category, keywords in TECH_MOAT_KEYWORDS.items():
        result[category] = any(k in text for k in keywords)

    return result


def filter_opportunities(opps: List[Dict]) -> List[Dict]:
    filtered = []

    for opp in opps:
        description = opp.get("description", "").lower()

        if any(
            keyword in description
            for group in TECH_MOAT_KEYWORDS.values()
            for keyword in group
        ):
            filtered.append(opp)

    return filtered
