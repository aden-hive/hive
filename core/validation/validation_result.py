from __future__ import annotations

from dataclasses import dataclass, field
from typing import Iterable

from validation.errors import ValidationError


@dataclass
class ValidationResult:
    valid: bool
    errors: list[ValidationError] = field(default_factory=list)

    @classmethod
    def from_errors(cls, errors: Iterable[ValidationError]) -> "ValidationResult":
        errors_list = list(errors)
        return cls(valid=len(errors_list) == 0, errors=errors_list)

    def to_dict(self) -> dict:
        return {
            "valid": self.valid,
            "errors": [error.to_dict() for error in self.errors],
        }
