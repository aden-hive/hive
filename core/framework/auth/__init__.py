"""Authentication and authorization framework."""

from .models import (
    User,
    UserCreate,
    UserLogin,
    UserResponse,
    Role,
    APIKey,
    AuditLog,
    Token,
    TokenPayload
)
from .jwt_handler import JWTHandler
from .rbac import Permission, Role as RoleDef, require_permission, require_role
from .audit_logger import AuditLogger
from .middleware import AuthMiddleware, get_current_user, require_scope

__all__ = [
    "User",
    "UserCreate",
    "UserLogin",
    "UserResponse",
    "Role",
    "APIKey",
    "AuditLog",
    "Token",
    "TokenPayload",
    "JWTHandler",
    "Permission",
    "Role as RoleDef",
    "require_permission",
    "require_role",
    "AuditLogger",
    "AuthMiddleware",
    "get_current_user",
    "require_scope",
]
