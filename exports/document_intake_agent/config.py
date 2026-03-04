"""
Agent configuration for Document Intake Agent.
Reads from ~/.hive/configuration.json for LLM defaults,
with agent-specific overrides here.
"""

# LLM Settings
MODEL = "claude-sonnet-4-5-20250929"  # Override if needed
MAX_TOKENS = 4096

# Confidence Thresholds
HIGH_CONFIDENCE_THRESHOLD = 0.85
MEDIUM_CONFIDENCE_THRESHOLD = 0.60

# Auto-routing rules
AUTO_PROCESS_CATEGORIES = [
    "invoice",
    "receipt",
    "expense_report",
]

HUMAN_REVIEW_CATEGORIES = [
    "contract",
    "compliance_doc",
    "tax_form",
]

# Supported file extensions
SUPPORTED_EXTENSIONS = {
    ".pdf": "pdf",
    ".png": "image",
    ".jpg": "image",
    ".jpeg": "image",
    ".tiff": "image",
    ".tif": "image",
    ".csv": "csv",
    ".docx": "docx",
    ".txt": "text",
    ".eml": "email",
}

# Document category → routing destination mapping
ROUTING_MAP = {
    "invoice": "accounts_payable",
    "receipt": "expense_management",
    "contract": "legal_review",
    "bank_statement": "finance_reconciliation",
    "tax_form": "tax_compliance",
    "purchase_order": "procurement",
    "expense_report": "expense_management",
    "onboarding_form": "human_resources",
    "compliance_doc": "compliance_team",
    "general": "general_inbox",
}

# Required fields per category (for validation)
REQUIRED_FIELDS = {
    "invoice": ["vendor_name", "invoice_number", "total_amount", "due_date"],
    "receipt": ["merchant_name", "total_amount", "date"],
    "contract": ["parties", "effective_date", "contract_type"],
    "bank_statement": ["account_number", "statement_period", "ending_balance"],
    "purchase_order": ["po_number", "vendor_name", "total_amount"],
    "expense_report": ["employee_name", "total_amount", "submission_date"],
    "tax_form": ["form_type", "tax_year", "taxpayer_name"],
}

# Budget controls
MAX_LLM_CALLS_PER_DOCUMENT = 5
MAX_COST_PER_DOCUMENT_USD = 0.50

# Advanced budget management
DAILY_BUDGET_LIMIT_USD = 10.0
ENABLE_MODEL_DEGRADATION = True

# Model quality requirements by task
TASK_QUALITY_REQUIREMENTS = {
    "document_classification": 0.8,    # High accuracy needed
    "field_extraction": 0.85,          # Very high accuracy needed
    "validation": 0.7,                 # Moderate accuracy acceptable
    "routing_decision": 0.75,          # Good accuracy needed
    "format_detection": 0.6,           # Lower accuracy acceptable
}

# Budget alert thresholds
BUDGET_WARNING_THRESHOLD = 0.8    # 80% of daily budget
BUDGET_CRITICAL_THRESHOLD = 0.95  # 95% of daily budget

# Cost optimization settings
ENABLE_COST_ANALYTICS = True
AUTO_MODEL_SELECTION = True       # Enable automatic model tier selection
QUALITY_VS_COST_PREFERENCE = "balanced"  # "quality", "balanced", "cost"