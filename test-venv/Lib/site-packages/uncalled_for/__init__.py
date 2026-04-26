"""Async dependency injection for Python functions.

Declare dependencies as parameter defaults. They resolve automatically when
the function is called through the dependency resolution context manager.
"""

from .annotations import get_annotation_dependencies
from .base import Dependency
from .functional import DependencyFactory, Depends
from .introspection import (
    get_dependency_parameters,
    get_signature,
)
from .resolution import FailedDependency, resolved_dependencies, without_dependencies
from .shared import Shared, SharedContext
from .validation import validate_dependencies

__all__ = [
    "Dependency",
    "DependencyFactory",
    "Depends",
    "FailedDependency",
    "Shared",
    "SharedContext",
    "get_annotation_dependencies",
    "get_dependency_parameters",
    "get_signature",
    "resolved_dependencies",
    "validate_dependencies",
    "without_dependencies",
]
