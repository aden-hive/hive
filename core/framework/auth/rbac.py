"""Role-Based Access Control (RBAC)."""

from typing import Dict, List, Set
from functools import wraps
from fastapi import HTTPException, Depends


class Permission:
    """Permission definition."""

    # Agent permissions
    AGENT_CREATE = "agent:create"
    AGENT_READ = "agent:read"
    AGENT_UPDATE = "agent:update"
    AGENT_DELETE = "agent:delete"
    AGENT_EXECUTE = "agent:execute"

    # Tool permissions
    TOOL_CREATE = "tool:create"
    TOOL_READ = "tool:read"
    TOOL_UPDATE = "tool:update"
    TOOL_DELETE = "tool:delete"
    TOOL_EXECUTE = "tool:execute"

    # Config permissions
    CONFIG_READ = "config:read"
    CONFIG_UPDATE = "config:update"

    # User management permissions
    USER_CREATE = "user:create"
    USER_READ = "user:read"
    USER_UPDATE = "user:update"
    USER_DELETE = "user:delete"

    # Admin permissions
    ADMIN = "admin"


class Role:
    """Role definitions with permissions."""

    ROLES: Dict[str, Set[str]] = {
        "free": {
            Permission.AGENT_READ,
            Permission.AGENT_CREATE,
            Permission.AGENT_EXECUTE,
            Permission.TOOL_READ,
            Permission.TOOL_EXECUTE,
            Permission.CONFIG_READ,
        },
        "pro": {
            # All free permissions
            *ROLES["free"],
            # Additional permissions
            Permission.AGENT_UPDATE,
            Permission.AGENT_DELETE,
            Permission.TOOL_CREATE,
            Permission.CONFIG_UPDATE,
        },
        "admin": {
            # All permissions
            Permission.ADMIN,
        }
    }

    @classmethod
    def get_permissions(cls, role_name: str) -> Set[str]:
        """Get permissions for a role."""
        return cls.ROLES.get(role_name, set())

    @classmethod
    def has_permission(cls, role_name: str, permission: str) -> bool:
        """Check if role has permission."""
        if role_name == "admin":
            return True
        return permission in cls.get_permissions(role_name)


def require_permission(*permissions: str):
    """Decorator to require specific permissions."""
    def decorator(func):
        @wraps(func)
        async def wrapper(*args, current_user, **kwargs):
            # Get user's role permissions
            user_permissions = set()
            for role in current_user.roles:
                user_permissions.update(Role.get_permissions(role.name))

            # Check if user has all required permissions
            for permission in permissions:
                if Permission.ADMIN not in user_permissions and permission not in user_permissions:
                    raise HTTPException(
                        status_code=403,
                        detail=f"Permission denied: {permission} required"
                    )

            return await func(*args, current_user=current_user, **kwargs)
        return wrapper
    return decorator


def require_role(*roles: str):
    """Decorator to require specific roles."""
    def decorator(func):
        @wraps(func)
        async def wrapper(*args, current_user, **kwargs):
            user_roles = {role.name for role in current_user.roles}

            if not any(role in user_roles for role in roles):
                raise HTTPException(
                    status_code=403,
                    detail=f"Role required: one of {', '.join(roles)}"
                )

            return await func(*args, current_user=current_user, **kwargs)
        return wrapper
    return decorator
