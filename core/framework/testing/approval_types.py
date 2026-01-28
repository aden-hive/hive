"""
Types for the approval workflow.

These types are used for both interactive CLI approval and
programmatic/MCP-based approval.
"""

from datetime import datetime
from enum import Enum
from typing import Any

from pydantic import BaseModel, Field


class ApprovalAction(str, Enum):
    """Actions a user can take on a generated test."""

    APPROVE = "approve"  # Accept as-is
    MODIFY = "modify"  # Accept with modifications
    REJECT = "reject"  # Decline
    SKIP = "skip"  # Leave pending (decide later)


class ApprovalRequest(BaseModel):
    """
    Request to approve/modify/reject a generated test.

    Used by both CLI and MCP interfaces.
    """

    test_id: str
    action: ApprovalAction
    modified_code: str | None = Field(default=None, description="New code if action is MODIFY")
    reason: str | None = Field(default=None, description="Rejection reason if action is REJECT")
    approved_by: str = "user"

    def validate_action(self) -> tuple[bool, str | None]:
        """
        Validate that the request has required fields for its action.

        Returns:
            Tuple of (is_valid, error_message)
        """
        if self.action == ApprovalAction.MODIFY and not self.modified_code:
            return False, "modified_code is required for MODIFY action"
        if self.action == ApprovalAction.REJECT and not self.reason:
            return False, "reason is required for REJECT action"
        return True, None


class ApprovalResult(BaseModel):
    """
    Result of processing an approval request.
    """

    test_id: str
    action: ApprovalAction
    success: bool
    message: str | None = None
    error: str | None = None
    timestamp: datetime = Field(default_factory=datetime.now)

    @classmethod
    def success_result(
        cls, test_id: str, action: ApprovalAction, message: str | None = None
    ) -> "ApprovalResult":
        """Create a successful result."""
        return cls(
            test_id=test_id,
            action=action,
            success=True,
            message=message,
        )

    @classmethod
    def error_result(cls, test_id: str, action: ApprovalAction, error: str) -> "ApprovalResult":
        """Create an error result."""
        return cls(
            test_id=test_id,
            action=action,
            success=False,
            error=error,
        )


class BatchApprovalRequest(BaseModel):
    """
    Request to approve multiple tests at once.

    Useful for MCP interface where user reviews all tests and submits decisions.
    """

    goal_id: str
    approvals: list[ApprovalRequest]

    def to_dict(self) -> dict[str, Any]:
        """Convert to dictionary for JSON serialization."""
        return {
            "goal_id": self.goal_id,
            "approvals": [a.model_dump() for a in self.approvals],
        }


class BatchApprovalResult(BaseModel):
    """
    Result of processing a batch approval request.
    """

    goal_id: str
    total: int
    approved: int
    modified: int
    rejected: int
    skipped: int
    errors: int
    results: list[ApprovalResult]

    def summary(self) -> str:
        """Return a summary string."""
        return (
            f"Processed {self.total} tests: "
            f"{self.approved} approved, "
            f"{self.modified} modified, "
            f"{self.rejected} rejected, "
            f"{self.skipped} skipped, "
            f"{self.errors} errors"
        )
