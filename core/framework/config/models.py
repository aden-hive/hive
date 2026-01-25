"""Configuration management models."""

from datetime import datetime
from typing import Optional, Dict, Any, List
from pydantic import BaseModel, Field
from uuid import UUID, uuid4


class Configuration(BaseModel):
    """Configuration model."""
    id: UUID = Field(default_factory=uuid4)
    environment: str
    service: str
    key: str
    value: Any
    type: str  # 'string', 'number', 'boolean', 'json'
    is_sensitive: bool = False
    version: int = 1
    created_at: datetime = Field(default_factory=datetime.utcnow)
    updated_at: datetime = Field(default_factory=datetime.utcnow)


class FeatureFlag(BaseModel):
    """Feature flag model."""
    id: UUID = Field(default_factory=uuid4)
    name: str
    description: Optional[str] = None
    enabled: bool = False
    rules: List[Dict[str, Any]] = []
    rollout_percentage: int = 100
    created_at: datetime = Field(default_factory=datetime.utcnow)
    updated_at: datetime = Field(default_factory=datetime.utcnow)


class ConfigHistory(BaseModel):
    """Configuration change history."""
    id: UUID = Field(default_factory=uuid4)
    config_id: UUID
    old_value: Any
    new_value: Any
    changed_by: Optional[UUID] = None
    changed_at: datetime = Field(default_factory=datetime.utcnow)


class FeatureFlagEvaluateRequest(BaseModel):
    """Feature flag evaluation request."""
    user_attributes: Dict[str, Any] = {}
