class CreditWorker:
    def __init__(self):
        self.role = "Credit Analysis Specialist"
        self.goal = "Evaluate financial history to determine loan risk."
        
    def evaluate_risk(self, applicant_data):
        print(f"[{self.role}] Calculating credit score for {applicant_data.get('name')}...")
        # actual credit scoring logic here
        
        return {
            "credit_score": 765,
            "risk_category": "Low",
            "approved_amount": 25000
        }