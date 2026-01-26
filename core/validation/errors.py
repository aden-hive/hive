from __future__ import annotations

from dataclasses import dataclass
from typing import Iterable


@dataclass(frozen=True)
class ValidationError(Exception):
    error_type: str
    nodes: tuple[str, ...]
    message: str

    def __str__(self) -> str:
        return self.message

    def to_dict(self) -> dict:
        return {
            "error_type": self.error_type,
            "nodes": list(self.nodes),
            "message": self.message,
        }


class GraphValidationError(Exception):
    def __init__(self, errors: Iterable[ValidationError]) -> None:
        self.errors = list(errors)
        message = "Graph validation failed with " + ", ".join(
            f"{err.error_type} ({', '.join(err.nodes) or 'graph'})" for err in self.errors
        )
        super().__init__(message)

    def to_dict(self) -> dict:
        return {
            "error_type": "graph_validation_failed",
            "errors": [error.to_dict() for error in self.errors],
        }
