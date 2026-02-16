"""Pydantic schemas for contract metadata."""

from datetime import date
from enum import Enum
from pydantic import BaseModel, Field


class ContractType(str, Enum):
    """Supported contract types."""
    NDA = "NDA"
    MUTUAL_NDA = "Mutual NDA"
    ONE_SIDED_NDA = "One-Sided NDA"
    UNKNOWN = "Unknown"


class Jurisdiction(str, Enum):
    """Common jurisdictions."""
    CALIFORNIA = "California"
    NEW_YORK = "New York"
    DELAWARE = "Delaware"
    TEXAS = "Texas"
    UK = "United Kingdom"
    EU = "European Union"
    UNKNOWN = "Unknown"


class ContractMetadata(BaseModel):
    """Metadata extracted from contract document."""
    
    contract_id: str = Field(description="Unique identifier for the contract")
    contract_type: ContractType = Field(description="Type of contract")
    jurisdiction: Jurisdiction = Field(description="Legal jurisdiction")
    confidence: float = Field(
        description="Confidence score for classification",
        ge=0.0,
        le=1.0
    )
    
    # Parties
    party_a: str | None = Field(None, description="First party name")
    party_b: str | None = Field(None, description="Second party name")
    
    # Dates
    effective_date: date | None = Field(None, description="Contract effective date")
    expiration_date: date | None = Field(None, description="Contract expiration date")
    
    # Document info
    page_count: int | None = Field(None, description="Number of pages")
    word_count: int | None = Field(None, description="Approximate word count")
    
    class Config:
        use_enum_values = True
