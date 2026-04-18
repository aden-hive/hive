
def score_opportunity(opp: dict) -> float:
    score = 0.0

    text = (opp.get("title", "") + " " + opp.get("description", "")).lower()

    # Intelligence (AI, NLP, Vision)
    if any(k in text for k in ["ai", "machine learning", "nlp", "computer vision"]):
        score += 0.3

    # Infrastructure (Cloud, SaaS)
    if any(k in text for k in ["cloud", "saas", "distributed"]):
        score += 0.2

    # Advanced Tech
    if any(k in text for k in ["robotics", "vision", "web3"]):
        score += 0.2

    # Budget signal
    if opp.get("budget") and opp["budget"] > 50000:
        score += 0.1

    # Urgency
    if "urgent" in text or "immediate" in text:
        score += 0.1

    # Enterprise signal
    if any(k in text for k in ["enterprise", "scalable", "platform"]):
        score += 0.1

    return min(score, 1.0)
