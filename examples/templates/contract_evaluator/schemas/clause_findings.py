"""Pydantic schemas for clause findings."""

from pydantic import BaseModel, Field


class ConfidentialityFinding(BaseModel):
    """Findings related to confidentiality clauses."""
    
    type: str = Field(description="mutual, one-sided, or unclear")
    scope: str = Field(description="Description of what's covered")
    exceptions: list[str] = Field(
        default_factory=list,
        description="List of exceptions (publicly available, etc.)"
    )
    duration_months: int | None = Field(None, description="Duration of confidentiality obligation")
    return_materials_required: bool = Field(False, description="Must materials be returned")
    
    risk_level: str = Field(description="low, medium, or high")
    concerns: list[str] = Field(default_factory=list, description="Specific concerns identified")


class LiabilityFinding(BaseModel):
    """Findings related to liability and indemnification."""
    
    cap_present: bool = Field(description="Whether liability is capped")
    cap_amount: str | None = Field(None, description="Cap amount if present")
    unlimited_liability: bool = Field(description="Whether liability is unlimited")
    indemnification_type: str = Field(description="mutual, one-sided, or none")
    insurance_required: bool = Field(False, description="Whether insurance is required")
    
    risk_level: str = Field(description="low, medium, or high")
    concerns: list[str] = Field(default_factory=list, description="Specific concerns")


class TermObligation(BaseModel):
    """Term and obligation findings."""
    
    duration_months: int | None = Field(None, description="Contract duration in months")
    auto_renewal: bool = Field(False, description="Whether contract auto-renews")
    notice_period_days: int | None = Field(None, description="Notice period for termination")
    termination_for_convenience: bool = Field(False, description="Can terminate without cause")
    
    key_obligations: list[str] = Field(
        default_factory=list,
        description="List of key obligations"
    )
    deliverables: list[str] = Field(
        default_factory=list,
        description="List of deliverables"
    )
    
    risk_level: str = Field(description="low, medium, or high")
    concerns: list[str] = Field(default_factory=list)


class ClauseFindings(BaseModel):
    """Aggregated findings from all clause analysis."""
    
    confidentiality: ConfidentialityFinding
    liability: LiabilityFinding
    terms: TermObligation
    
    # Additional extracted information
    key_dates: dict[str, str] = Field(
        default_factory=dict,
        description="Dictionary of important dates"
    )
    financial_terms: dict[str, str] = Field(
        default_factory=dict,
        description="Any financial terms found"
    )
