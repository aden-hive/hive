"""Audit logging for authentication and authorization."""

from typing import Optional, Dict, Any
from datetime import datetime
from uuid import UUID
import json

from .models import AuditLog


class AuditLogger:
    """Audit logger for tracking security events."""

    def __init__(self):
        self.logs: list[AuditLog] = []

    async def log(
        self,
        action: str,
        user_id: Optional[UUID] = None,
        resource_type: Optional[str] = None,
        resource_id: Optional[UUID] = None,
        ip_address: Optional[str] = None,
        user_agent: Optional[str] = None,
        metadata: Dict[str, Any] = None
    ) -> AuditLog:
        """Log an audit event."""
        log = AuditLog(
            user_id=user_id,
            action=action,
            resource_type=resource_type,
            resource_id=resource_id,
            ip_address=ip_address,
            user_agent=user_agent,
            metadata=metadata or {}
        )
        self.logs.append(log)

        # In production, persist to database
        # await database.audit_logs.insert(log.dict())

        return log

    async def log_login(
        self,
        user_id: UUID,
        success: bool,
        ip_address: Optional[str] = None,
        user_agent: Optional[str] = None
    ) -> AuditLog:
        """Log user login attempt."""
        return await self.log(
            action="login:success" if success else "login:failed",
            user_id=user_id,
            ip_address=ip_address,
            user_agent=user_agent,
            metadata={"timestamp": datetime.utcnow().isoformat()}
        )

    async def log_logout(
        self,
        user_id: UUID,
        ip_address: Optional[str] = None
    ) -> AuditLog:
        """Log user logout."""
        return await self.log(
            action="logout",
            user_id=user_id,
            ip_address=ip_address
        )

    async def log_permission_check(
        self,
        user_id: UUID,
        permission: str,
        granted: bool,
        resource_type: Optional[str] = None,
        resource_id: Optional[UUID] = None
    ) -> AuditLog:
        """Log permission check."""
        return await self.log(
            action="permission_check",
            user_id=user_id,
            resource_type=resource_type,
            resource_id=resource_id,
            metadata={
                "permission": permission,
                "granted": granted
            }
        )

    async def log_api_access(
        self,
        user_id: Optional[UUID],
        method: str,
        path: str,
        status_code: int,
        ip_address: Optional[str] = None
    ) -> AuditLog:
        """Log API access."""
        return await self.log(
            action="api_access",
            user_id=user_id,
            resource_type=path,
            metadata={
                "method": method,
                "status_code": status_code
            },
            ip_address=ip_address
        )

    async def get_user_logs(
        self,
        user_id: UUID,
        limit: int = 100
    ) -> list[AuditLog]:
        """Get audit logs for a user."""
        user_logs = [log for log in self.logs if log.user_id == user_id]
        return sorted(user_logs, key=lambda x: x.timestamp, reverse=True)[:limit]

    async def get_logs_by_action(
        self,
        action: str,
        limit: int = 100
    ) -> list[AuditLog]:
        """Get audit logs by action type."""
        logs = [log for log in self.logs if log.action == action]
        return sorted(logs, key=lambda x: x.timestamp, reverse=True)[:limit]
