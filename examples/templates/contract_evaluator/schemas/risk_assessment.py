"""Pydantic schema for risk assessment."""

from pydantic import BaseModel, Field


class RiskAssessment(BaseModel):
    """Overall risk assessment of the contract."""
    
    overall_risk_score: float = Field(
        description="Overall risk score from 1-10",
        ge=1.0,
        le=10.0
    )
    
    confidentiality_risk: float = Field(description="Risk score for confidentiality", ge=1.0, le=10.0)
    liability_risk: float = Field(description="Risk score for liability", ge=1.0, le=10.0)
    terms_risk: float = Field(description="Risk score for terms and obligations", ge=1.0, le=10.0)
    
    critical_issues: list[str] = Field(
        default_factory=list,
        description="List of critical issues requiring immediate attention"
    )
    
    moderate_issues: list[str] = Field(
        default_factory=list,
        description="List of moderate concerns"
    )
    
    recommendations: list[str] = Field(
        default_factory=list,
        description="Recommended actions or changes"
    )
    
    human_review_required: bool = Field(
        description="Whether human legal review is required"
    )
    human_review_reason: str | None = Field(
        None,
        description="Reason why human review is needed"
    )
    
    compliance_flags: list[str] = Field(
        default_factory=list,
        description="Potential compliance issues flagged"
    )
