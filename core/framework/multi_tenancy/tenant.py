"""Multi-tenancy support."""

from typing import Optional
from contextvars import ContextVar
from pydantic import BaseModel
from uuid import UUID, uuid4
from datetime import datetime


# Context variable for tenant
current_tenant_id: ContextVar[Optional[str]] = ContextVar('current_tenant_id', default=None)


class Tenant(BaseModel):
    """Tenant model."""
    id: UUID = uuid4()
    name: str
    slug: str
    status: str = "active"
    plan: str = "free"

    # Resource quotas
    quota_agents: int = 10
    quota_nodes_per_agent: int = 50
    quota_storage_gb: int = 10
    quota_api_calls_per_day: int = 1000

    created_at: datetime = datetime.utcnow()


class TenantContext:
    """Tenant context manager."""

    def __init__(self, tenant_id: str):
        self.tenant_id = tenant_id

    async def __aenter__(self):
        current_tenant_id.set(self.tenant_id)
        return self

    async def __aexit__(self, *args):
        current_tenant_id.set(None)


def get_current_tenant_id() -> Optional[str]:
    """Get current tenant from context."""
    return current_tenant_id.get()


class ResourceQuotaManager:
    """Manage tenant resource quotas."""

    def __init__(self):
        self._usage: Dict[str, Dict[str, int]] = {}

    async def check_quota(self, tenant_id: str, resource: str) -> bool:
        """Check if tenant has quota."""
        # In production, check against tenant.quota_* values
        current = self._usage.get(tenant_id, {}).get(resource, 0)
        # Simplified - would fetch tenant quota from DB
        return current < 1000

    async def consume_quota(self, tenant_id: str, resource: str, amount: int = 1) -> bool:
        """Consume quota resource."""
        if await self.check_quota(tenant_id, resource):
            if tenant_id not in self._usage:
                self._usage[tenant_id] = {}
            self._usage[tenant_id][resource] = self._usage[tenant_id].get(resource, 0) + amount
            return True
        raise Exception("Quota exceeded")

    async def reset_daily_quotas(self) -> None:
        """Reset daily quotas."""
        self._usage.clear()
