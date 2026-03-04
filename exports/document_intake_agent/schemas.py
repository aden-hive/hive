"""
Pydantic schemas for the Universal Document Intake & Action Agent.

These models define the structured data contracts for:
- Document input (what comes in)
- Extraction results (what we pull out)
- Classification results (what type of document)
- Validation results (is the data clean)
- Routing decisions (where does it go)
- Final output (the complete processed result)
"""

from pydantic import BaseModel, Field
from enum import Enum
from typing import Optional, List, Dict, Any
from datetime import datetime


class DocumentFormat(str, Enum):
    PDF = "pdf"
    IMAGE = "image"       # png, jpg, tiff
    EMAIL = "email"       # .eml or raw text
    CSV = "csv"
    DOCX = "docx"
    TEXT = "text"
    UNKNOWN = "unknown"


class DocumentCategory(str, Enum):
    INVOICE = "invoice"
    RECEIPT = "receipt"
    CONTRACT = "contract"
    BANK_STATEMENT = "bank_statement"
    TAX_FORM = "tax_form"
    PURCHASE_ORDER = "purchase_order"
    EXPENSE_REPORT = "expense_report"
    ONBOARDING_FORM = "onboarding_form"
    COMPLIANCE_DOC = "compliance_doc"
    GENERAL = "general"


class ConfidenceLevel(str, Enum):
    HIGH = "high"          # >= 0.85 — auto-proceed
    MEDIUM = "medium"      # 0.60-0.85 — proceed with flag
    LOW = "low"            # < 0.60 — human review required


class RoutingAction(str, Enum):
    AUTO_PROCESS = "auto_process"
    HUMAN_REVIEW = "human_review"
    REJECT = "reject"
    ESCALATE = "escalate"


class DocumentInput(BaseModel):
    """What arrives at the agent."""
    file_path: str = Field(..., description="Path to the document file")
    source_channel: str = Field(default="upload", description="How it arrived: upload, email, api, webhook")
    metadata: Dict[str, Any] = Field(default_factory=dict, description="Any additional context")
    received_at: datetime = Field(default_factory=datetime.utcnow)


class ExtractedEntity(BaseModel):
    """A single extracted data point."""
    field_name: str          # e.g., "vendor_name", "total_amount", "due_date"
    value: str               # The extracted value
    confidence: float        # 0.0 to 1.0
    page_number: Optional[int] = None
    bounding_box: Optional[Dict[str, float]] = None  # For OCR: {x, y, width, height}


class ExtractionResult(BaseModel):
    """Everything extracted from a document."""
    entities: List[ExtractedEntity] = []
    raw_text: str = ""
    page_count: int = 0
    extraction_method: str = ""  # "ocr", "text_parse", "llm", "hybrid"
    processing_time_ms: float = 0.0


class ClassificationResult(BaseModel):
    """What type of document is this."""
    category: DocumentCategory
    confidence: float
    confidence_level: ConfidenceLevel
    reasoning: str = ""
    secondary_categories: List[Dict[str, Any]] = []  # [{"category": ..., "confidence": ...}]


class ValidationResult(BaseModel):
    """Are the extracted fields valid and complete."""
    is_valid: bool
    errors: List[str] = []
    warnings: List[str] = []
    missing_fields: List[str] = []
    completeness_score: float = 0.0  # 0.0 to 1.0


class RoutingDecision(BaseModel):
    """Where should this document go next."""
    action: RoutingAction
    destination: str = ""          # e.g., "accounts_payable", "legal_review", "compliance"
    priority: str = "normal"       # "urgent", "high", "normal", "low"
    reason: str = ""
    requires_human: bool = False
    human_review_fields: List[str] = []  # Which specific fields need human eyes


class ProcessedDocument(BaseModel):
    """The complete output — everything about this document."""
    document_id: str
    input: DocumentInput
    format_detected: DocumentFormat
    extraction: ExtractionResult
    classification: ClassificationResult
    validation: ValidationResult
    routing: RoutingDecision
    processed_at: datetime = Field(default_factory=datetime.utcnow)
    processing_duration_ms: float = 0.0
    agent_version: str = "0.1.0"