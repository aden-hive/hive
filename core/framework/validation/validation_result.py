from __future__ import annotations

from dataclasses import dataclass, field

from framework.validation.errors import ValidationError


@dataclass
class ValidationResult:
    valid: bool
    errors: list[ValidationError] = field(default_factory=list)

    def to_dict(self) -> dict:
        return {
            "valid": self.valid,
            "errors": [error.to_dict() for error in self.errors],
        }
