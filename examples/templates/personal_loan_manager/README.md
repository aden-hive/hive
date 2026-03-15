# BFSI Personal Loan Manager Agent

## Overview
The Personal Loan Manager is a multi-agent system built on the Aden Hive framework. It automates the B2B/B2C workflow for personal loan approvals by using a Queen Bee orchestrator to manage specialized Worker Bee nodes for compliance and risk assessment.

## Architecture
This agent utilizes the strict **Queen Bee and Worker Bee** pattern:
* **Queen Bee (`agent.py`)**: Orchestrates the workflow, evaluates success criteria, enforces constraints (like strict financial accuracy), and routes the applicant through the pipeline.
* **Worker Bees (`nodes/`)**: Specialized execution nodes that handle isolated, domain-specific tasks.

## Workflow Nodes
1. **Intake**: Gathers initial applicant data and loan requirements.
2. **KYC Verification (`kyc_worker.py`)**: Evaluates applicant identity and AML (Anti-Money Laundering) compliance. If this fails, the applicant is instantly routed to rejection.
3. **Credit Risk Analysis (`credit_worker.py`)**: Analyzes financial history to determine a credit score, approved amount, and risk category.
4. **Decision Report**: Generates the final approval or rejection report based strictly on the Worker Bee evaluations.

## Graph Flow
`Intake` -> `KYC Verification` -> `Credit Risk Analysis` (conditional on KYC pass) -> `Decision Report`