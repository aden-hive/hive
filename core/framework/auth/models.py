"""Authentication and authorization models."""

from datetime import datetime
from typing import Optional, Dict, Any
from pydantic import BaseModel, EmailStr, Field
from uuid import UUID, uuid4


class User(BaseModel):
    """User model."""
    id: UUID = Field(default_factory=uuid4)
    email: EmailStr
    name: str
    mfa_enabled: bool = False
    is_active: bool = True
    created_at: datetime = Field(default_factory=datetime.utcnow)
    updated_at: datetime = Field(default_factory=datetime.utcnow)


class UserCreate(BaseModel):
    """User creation model."""
    email: EmailStr
    password: str = Field(min_length=8)
    name: str


class UserLogin(BaseModel):
    """User login model."""
    email: EmailStr
    password: str


class UserResponse(BaseModel):
    """User response model (without sensitive data)."""
    id: UUID
    email: str
    name: str
    mfa_enabled: bool
    is_active: bool
    created_at: datetime


class Role(BaseModel):
    """Role model."""
    id: UUID = Field(default_factory=uuid4)
    name: str
    description: Optional[str] = None
    permissions: Dict[str, bool] = {}
    created_at: datetime = Field(default_factory=datetime.utcnow)


class APIKey(BaseModel):
    """API Key model."""
    id: UUID = Field(default_factory=uuid4)
    user_id: UUID
    key_hash: str
    name: str
    scopes: Dict[str, bool] = {}
    expires_at: Optional[datetime] = None
    last_used_at: Optional[datetime] = None
    created_at: datetime = Field(default_factory=datetime.utcnow)


class AuditLog(BaseModel):
    """Audit log model."""
    id: UUID = Field(default_factory=uuid4)
    user_id: Optional[UUID] = None
    action: str
    resource_type: Optional[str] = None
    resource_id: Optional[UUID] = None
    ip_address: Optional[str] = None
    user_agent: Optional[str] = None
    metadata: Dict[str, Any] = {}
    timestamp: datetime = Field(default_factory=datetime.utcnow)


class Token(BaseModel):
    """JWT Token model."""
    access_token: str
    refresh_token: str
    token_type: str = "bearer"
    expires_in: int


class TokenPayload(BaseModel):
    """JWT Token payload."""
    sub: UUID  # user_id
    email: str
    exp: int  # expiration timestamp
    iat: int  # issued at timestamp
    scopes: list[str] = []
