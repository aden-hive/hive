def define_loan_workflow():
    workflow = {
        "name": "Personal Loan Processing Pipeline",
        "nodes": [
            "intake_application",
            "verify_kyc",
            "evaluate_credit",
            "final_decision"
        ],
        "edges": [
            ("intake_application", "verify_kyc"),
            ("verify_kyc", "evaluate_credit"),
            ("evaluate_credit", "final_decision")
        ]
    }
    return workflow