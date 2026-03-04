class LoanQueenBee:
    def __init__(self):
        self.role = "Lead Loan Orchestrator"
        self.goal = "Manage personal loan applications and delegate verification tasks."
        
    def assign_task(self, worker_type, application_data):
        print(f"Queen Bee: Assigning task to {worker_type} worker...")
        
        if worker_type == "kyc_specialist":
            return self._call_kyc_worker(application_data)
            
        elif worker_type == "credit_specialist":
            return self._call_credit_worker(application_data)
            
    def _call_kyc_worker(self, data):
        print("Worker Bee (KYC): Processing identity documents...")
        return {"kyc_status": "Approved"}
        
    def _call_credit_worker(self, data):
        print("Worker Bee (Credit): Analyzing financial history...")
        return {"credit_score": 750, "risk_level": "Low"}