from __future__ import annotations

from typing import Any, Optional
from pydantic import BaseModel, Field

CONTRACT_VERSION = "0.1.0"


class ArtifactError(BaseModel):
    code: str = Field(..., description="Stable error code, e.g. INVALID_SCHEMA, IO_ERROR, DEP_MISSING")
    message: str
    details: Optional[Any] = None


class ArtifactResult(BaseModel):
    success: bool
    output_path: Optional[str] = None
    contract_version: str = CONTRACT_VERSION
    error: Optional[ArtifactError] = None
    metadata: dict[str, Any] = Field(default_factory=dict)
