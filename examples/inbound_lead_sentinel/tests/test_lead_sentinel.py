import os
import sys
sys.path.append(os.path.dirname(os.path.dirname(__file__)))
from agent import inbound_lead_pipeline

def test_high_intent_lead():
    lead = {"name": "John", "email": "john@startup.com"}
    result = inbound_lead_pipeline(lead)
    assert result["status"] == "sent_to_salesforce"
