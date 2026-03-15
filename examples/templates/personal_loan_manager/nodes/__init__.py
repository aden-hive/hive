"""Worker nodes for Personal Loan Manager."""
from .kyc_worker import execute as kyc_execute
from .credit_worker import execute as credit_execute

__all__ = ["kyc_execute", "credit_execute"]