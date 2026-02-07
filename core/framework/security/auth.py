"""Authentication and Authorization.

Provides role-based access control (RBAC) for the framework:
- Permission-based access control
- Context-aware authorization
- Decorator-based enforcement

Usage:
    from framework.security import require_permission, Permission, AuthContext

    @require_permission(Permission.EXECUTE_GRAPH)
    async def run_graph(ctx: AuthContext, graph: GraphSpec):
        ...
"""

import functools
import logging
from dataclasses import dataclass, field
from enum import StrEnum
from typing import Callable, TypeVar, Any

logger = logging.getLogger(__name__)

F = TypeVar("F", bound=Callable)


class Permission(StrEnum):
    """Framework permissions."""

    # Graph operations
    EXECUTE_GRAPH = "graph:execute"
    CREATE_GRAPH = "graph:create"
    DELETE_GRAPH = "graph:delete"
    MODIFY_GRAPH = "graph:modify"

    # Node operations
    EXECUTE_NODE = "node:execute"
    CREATE_NODE = "node:create"

    # Memory operations
    READ_MEMORY = "memory:read"
    WRITE_MEMORY = "memory:write"
    DELETE_MEMORY = "memory:delete"

    # LLM operations
    CALL_LLM = "llm:call"
    USE_TOOLS = "llm:tools"

    # Tool operations
    EXECUTE_TOOL = "tool:execute"
    REGISTER_TOOL = "tool:register"

    # Secret operations
    READ_SECRETS = "secret:read"
    WRITE_SECRETS = "secret:write"
    ROTATE_SECRETS = "secret:rotate"

    # Admin operations
    VIEW_AUDIT_LOG = "admin:audit"
    MANAGE_USERS = "admin:users"
    CHANGE_CONFIG = "admin:config"


class Role(StrEnum):
    """Pre-defined roles with permission sets."""

    VIEWER = "viewer"  # Read-only access
    OPERATOR = "operator"  # Execute but not modify
    DEVELOPER = "developer"  # Full development access
    ADMIN = "admin"  # Full administrative access
    SERVICE = "service"  # Service account (limited)


# Default role permissions
ROLE_PERMISSIONS: dict[Role, set[Permission]] = {
    Role.VIEWER: {
        Permission.READ_MEMORY,
        Permission.VIEW_AUDIT_LOG,
    },
    Role.OPERATOR: {
        Permission.READ_MEMORY,
        Permission.EXECUTE_GRAPH,
        Permission.EXECUTE_NODE,
        Permission.CALL_LLM,
        Permission.EXECUTE_TOOL,
        Permission.VIEW_AUDIT_LOG,
    },
    Role.DEVELOPER: {
        Permission.READ_MEMORY,
        Permission.WRITE_MEMORY,
        Permission.EXECUTE_GRAPH,
        Permission.CREATE_GRAPH,
        Permission.MODIFY_GRAPH,
        Permission.EXECUTE_NODE,
        Permission.CREATE_NODE,
        Permission.CALL_LLM,
        Permission.USE_TOOLS,
        Permission.EXECUTE_TOOL,
        Permission.REGISTER_TOOL,
        Permission.READ_SECRETS,
        Permission.VIEW_AUDIT_LOG,
    },
    Role.ADMIN: set(Permission),  # All permissions
    Role.SERVICE: {
        Permission.EXECUTE_GRAPH,
        Permission.EXECUTE_NODE,
        Permission.CALL_LLM,
        Permission.EXECUTE_TOOL,
        Permission.READ_MEMORY,
        Permission.WRITE_MEMORY,
    },
}


@dataclass
class AuthContext:
    """Authentication and authorization context.

    Passed to protected functions to identify the caller
    and their permissions.
    """

    user_id: str
    roles: set[Role] = field(default_factory=set)
    permissions: set[Permission] = field(default_factory=set)
    session_id: str | None = None
    ip_address: str | None = None
    metadata: dict[str, Any] = field(default_factory=dict)

    @classmethod
    def anonymous(cls) -> "AuthContext":
        """Create anonymous context with no permissions."""
        return cls(user_id="anonymous", roles=set(), permissions=set())

    @classmethod
    def system(cls) -> "AuthContext":
        """Create system context with all permissions."""
        return cls(
            user_id="system",
            roles={Role.ADMIN},
            permissions=set(Permission),
        )

    @classmethod
    def for_role(cls, user_id: str, role: Role | str) -> "AuthContext":
        """Create context for a specific role."""
        if isinstance(role, str):
            role = Role(role)
        return cls(
            user_id=user_id,
            roles={role},
            permissions=ROLE_PERMISSIONS.get(role, set()),
        )

    def has_permission(self, permission: Permission) -> bool:
        """Check if context has a specific permission."""
        # Check direct permissions
        if permission in self.permissions:
            return True
        # Check role-based permissions
        for role in self.roles:
            if permission in ROLE_PERMISSIONS.get(role, set()):
                return True
        return False

    def has_role(self, role: Role) -> bool:
        """Check if context has a specific role."""
        return role in self.roles


class AuthorizationError(Exception):
    """Raised when authorization check fails."""

    def __init__(
        self,
        message: str,
        required_permission: Permission | None = None,
        user_id: str | None = None,
    ):
        super().__init__(message)
        self.required_permission = required_permission
        self.user_id = user_id


def check_permission(
    ctx: AuthContext,
    permission: Permission,
    *,
    resource: str | None = None,
    raise_on_deny: bool = True,
) -> bool:
    """Check if context has required permission.

    Args:
        ctx: Authorization context
        permission: Required permission
        resource: Optional resource identifier for logging
        raise_on_deny: If True, raise AuthorizationError on failure

    Returns:
        True if authorized

    Raises:
        AuthorizationError: If not authorized and raise_on_deny=True
    """
    from framework.security.audit import audit_log, SecurityEvent

    has_perm = ctx.has_permission(permission)

    if has_perm:
        # Log successful authorization
        audit_log(
            SecurityEvent.AUTHZ_GRANTED,
            user_id=ctx.user_id,
            session_id=ctx.session_id,
            resource=resource,
            action=permission.value,
        )
        return True
    else:
        # Log denied authorization
        audit_log(
            SecurityEvent.AUTHZ_DENIED,
            user_id=ctx.user_id,
            session_id=ctx.session_id,
            resource=resource,
            action=permission.value,
            outcome="failure",
        )

        logger.warning(
            f"Authorization denied: {ctx.user_id} lacks {permission.value}",
            extra={
                "user_id": ctx.user_id,
                "permission": permission.value,
                "resource": resource,
            },
        )

        if raise_on_deny:
            raise AuthorizationError(
                f"Permission denied: {permission.value}",
                required_permission=permission,
                user_id=ctx.user_id,
            )

        return False


def require_permission(*permissions: Permission) -> Callable[[F], F]:
    """Decorator to require permissions for a function.

    The decorated function must accept AuthContext as first argument.

    Usage:
        @require_permission(Permission.EXECUTE_GRAPH)
        async def run_graph(ctx: AuthContext, graph: GraphSpec):
            ...
    """

    def decorator(func: F) -> F:
        @functools.wraps(func)
        async def async_wrapper(ctx: AuthContext, *args, **kwargs):
            for perm in permissions:
                check_permission(ctx, perm, resource=func.__name__)
            return await func(ctx, *args, **kwargs)

        @functools.wraps(func)
        def sync_wrapper(ctx: AuthContext, *args, **kwargs):
            for perm in permissions:
                check_permission(ctx, perm, resource=func.__name__)
            return func(ctx, *args, **kwargs)

        import asyncio
        if asyncio.iscoroutinefunction(func):
            return async_wrapper  # type: ignore
        return sync_wrapper  # type: ignore

    return decorator


__all__ = [
    "Permission",
    "Role",
    "AuthContext",
    "AuthorizationError",
    "ROLE_PERMISSIONS",
    "check_permission",
    "require_permission",
]
