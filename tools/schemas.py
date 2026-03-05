"""
Schemas and data models for universal document processing system.
"""
from typing import Dict, List, Optional, Union
from datetime import datetime
from pydantic import BaseModel, Field
from enum import Enum


class DocumentType(str, Enum):
    """Supported document types."""
    INVOICE = "invoice"
    CONTRACT = "contract"
    RECEIPT = "receipt"
    BANK_STATEMENT = "bank_statement"
    FORM = "form"
    RESUME = "resume"
    REPORT = "report"
    UNKNOWN = "unknown"


class ProcessingStatus(str, Enum):
    """Processing status indicators."""
    PENDING = "pending"
    PROCESSING = "processing"
    COMPLETED = "completed"
    FAILED = "failed"
    NEEDS_REVIEW = "needs_review"


class ConfidenceLevel(str, Enum):
    """Confidence level categories."""
    LOW = "low"      # < 0.7
    MEDIUM = "medium"  # 0.7 - 0.85
    HIGH = "high"    # > 0.85


class ExtractedEntity(BaseModel):
    """Individual extracted field/entity."""
    field_name: str = Field(..., description="Name of the field")
    value: Union[str, float, int, datetime, None] = Field(..., description="Extracted value")
    confidence: float = Field(..., ge=0.0, le=1.0, description="Confidence score")
    context: str = Field(..., description="Where this was found in the document")
    validation_status: str = Field(default="unchecked", description="Validation result")


class DocumentClassification(BaseModel):
    """Document classification results."""
    category: DocumentType = Field(..., description="Document category")
    confidence: float = Field(..., ge=0.0, le=1.0, description="Classification confidence")
    confidence_level: ConfidenceLevel = Field(..., description="Confidence level")
    reasoning: str = Field(..., description="Why this classification was chosen")
    key_indicators: List[str] = Field(default_factory=list, description="Evidence supporting classification")
    processing_time_ms: int = Field(..., description="Processing time in milliseconds")


class ProcessingMetrics(BaseModel):
    """Performance and quality metrics."""
    start_time: datetime = Field(..., description="Processing start time")
    end_time: Optional[datetime] = Field(None, description="Processing end time")
    processing_time_ms: Optional[int] = Field(None, description="Total processing time")
    extraction_confidence_avg: float = Field(0.0, ge=0.0, le=1.0, description="Average extraction confidence")
    validation_passed: bool = Field(False, description="Whether validation passed")
    routing_decision: str = Field(..., description="Where document was routed")


class ProcessedDocument(BaseModel):
    """
    Main output schema for processed documents.
    Contains all results from document processing pipeline.
    """
    document_id: str = Field(..., description="Unique document identifier")
    original_filename: str = Field(..., description="Original file name")
    file_path: str = Field(..., description="Path to original document")
    file_size_bytes: int = Field(..., description="File size in bytes")
    format_detected: str = Field(..., description="Detected file format")
    processing_status: ProcessingStatus = Field(..., description="Current processing status")
    
    # Core processing results
    classification: DocumentClassification = Field(..., description="Document classification")
    extracted_entities: List[ExtractedEntity] = Field(default_factory=list, description="Extracted data fields")
    raw_content: str = Field(..., description="Raw text content from document")
    
    # Quality control
    confidence_level: ConfidenceLevel = Field(..., description="Overall confidence level")
    validation_errors: List[str] = Field(default_factory=list, description="Validation errors found")
    
    # Processing metadata
    metrics: ProcessingMetrics = Field(..., description="Processing performance metrics")
    
    # Routing information
    routing_destination: str = Field(..., description="Where document should be routed")
    requires_human_review: bool = Field(..., description="Whether human review is needed")
    
    # Audit trail
    processing_history: List[Dict] = Field(default_factory=list, description="Processing steps taken")
    created_at: datetime = Field(default_factory=datetime.now, description="When processed")