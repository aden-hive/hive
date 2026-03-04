"""
All LLM prompts for the Document Intake Agent.
Kept separate for easy iteration and testing.
"""

CLASSIFICATION_PROMPT = """You are a document classification expert. Given the following extracted text from a document, classify it into exactly one category.

Categories:
- invoice: Bills from vendors/suppliers requesting payment
- receipt: Proof of purchase/payment already made
- contract: Legal agreements between parties
- bank_statement: Account statements from financial institutions
- tax_form: Tax-related documents (W-9, 1099, etc.)
- purchase_order: Orders placed to vendors
- expense_report: Employee expense claims
- onboarding_form: New employee/customer onboarding documents
- compliance_doc: Regulatory or compliance-related documents
- general: Anything that doesn't fit the above

Respond ONLY with valid JSON:
{{
    "category": "<category_name>",
    "confidence": <0.0 to 1.0>,
    "reasoning": "<brief explanation>",
    "secondary_categories": [
        {{"category": "<name>", "confidence": <score>}}
    ]
}}

Document text:
---
{document_text}
---"""


EXTRACTION_PROMPT = """You are a document data extraction expert. Given the following document text and its classification, extract all relevant structured fields.

Document category: {category}
Expected fields for this category: {expected_fields}

Extract every field you can find. For each field, provide:
- field_name: The standardized field name
- value: The extracted value (as a string)
- confidence: Your confidence in the extraction (0.0 to 1.0)

Respond ONLY with valid JSON:
{{
    "entities": [
        {{"field_name": "<name>", "value": "<value>", "confidence": <score>}}
    ]
}}

Also extract any additional fields beyond the expected ones that seem important.

Document text:
---
{document_text}
---"""


VALIDATION_PROMPT = """You are a document validation expert. Given the extracted data from a {category} document, validate the following:

1. Are all required fields present? Required: {required_fields}
2. Are the values in valid formats? (dates should be dates, amounts should be numbers, etc.)
3. Are there any logical inconsistencies? (e.g., due date before invoice date)
4. Are there any suspicious or unusual values?

Extracted data:
{extracted_data}

Respond ONLY with valid JSON:
{{
    "is_valid": <true/false>,
    "errors": ["<critical issues>"],
    "warnings": ["<non-critical concerns>"],
    "missing_fields": ["<required fields not found>"],
    "completeness_score": <0.0 to 1.0>
}}"""