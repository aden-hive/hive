# examples/inbound_lead_sentinel/agent.py

def enrich_lead(lead):
    # Mock Apollo enrichment
    lead["company_size"] = 250
    lead["industry"] = "SaaS"
    return lead

def score_lead(lead):
    score = 0
    if lead["company_size"] > 100:
        score += 50
    if lead["industry"] == "SaaS":
        score += 50
    return score

def route_to_salesforce(lead, score):
    if score >= 80:
        return {"status": "sent_to_salesforce", "lead": lead}
    return {"status": "discarded", "lead": lead}

def inbound_lead_pipeline(lead):
    lead = enrich_lead(lead)
    score = score_lead(lead)
    return route_to_salesforce(lead, score)
