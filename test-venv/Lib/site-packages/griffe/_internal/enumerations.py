# This module contains all the enumerations of the package.

from __future__ import annotations

from enum import Enum


class LogLevel(str, Enum):
    """Enumeration of available log levels."""

    trace = "trace"
    """The TRACE log level."""
    debug = "debug"
    """The DEBUG log level."""
    info = "info"
    """The INFO log level."""
    success = "success"
    """The SUCCESS log level."""
    warning = "warning"
    """The WARNING log level."""
    error = "error"
    """The ERROR log level."""
    critical = "critical"
    """The CRITICAL log level."""


class DocstringSectionKind(str, Enum):
    """Enumeration of the possible docstring section kinds."""

    text = "text"
    """Text section."""
    parameters = "parameters"
    """Parameters section."""
    other_parameters = "other parameters"
    """Other parameters (keyword arguments) section."""
    type_parameters = "type parameters"
    """Type parameters section."""
    raises = "raises"
    """Raises (exceptions) section."""
    warns = "warns"
    """Warnings section."""
    returns = "returns"
    """Returned value(s) section."""
    yields = "yields"
    """Yielded value(s) (generators) section."""
    receives = "receives"
    """Received value(s) (generators) section."""
    examples = "examples"
    """Examples section."""
    attributes = "attributes"
    """Attributes section."""
    functions = "functions"
    """Functions section."""
    classes = "classes"
    """Classes section."""
    type_aliases = "type aliases"
    """Type aliases section."""
    modules = "modules"
    """Modules section."""
    deprecated = "deprecated"
    """Deprecation section."""
    admonition = "admonition"
    """Admonition block."""


class ParameterKind(str, Enum):
    """Enumeration of the different parameter kinds."""

    positional_only = "positional-only"
    """Positional-only parameter."""
    positional_or_keyword = "positional or keyword"
    """Positional or keyword parameter."""
    var_positional = "variadic positional"
    """Variadic positional parameter."""
    keyword_only = "keyword-only"
    """Keyword-only parameter."""
    var_keyword = "variadic keyword"
    """Variadic keyword parameter."""


class TypeParameterKind(str, Enum):
    """Enumeration of the different type parameter kinds."""

    type_var = "type-var"
    """Type variable."""
    type_var_tuple = "type-var-tuple"
    """Type variable tuple."""
    param_spec = "param-spec"
    """Parameter specification variable."""


class Kind(str, Enum):
    """Enumeration of the different object kinds."""

    MODULE = "module"
    """Modules."""
    CLASS = "class"
    """Classes."""
    FUNCTION = "function"
    """Functions and methods."""
    ATTRIBUTE = "attribute"
    """Attributes and properties."""
    ALIAS = "alias"
    """Aliases (imported objects)."""
    TYPE_ALIAS = "type alias"
    """Type aliases."""


class ExplanationStyle(str, Enum):
    """Enumeration of the possible styles for explanations."""

    ONE_LINE = "oneline"
    """Explanations on one-line."""
    VERBOSE = "verbose"
    """Explanations on multiple lines."""
    MARKDOWN = "markdown"
    """Explanations in Markdown, adapted to changelogs."""
    GITHUB = "github"
    """Explanation as GitHub workflow commands warnings, adapted to CI."""


class BreakageKind(str, Enum):
    """Enumeration of the possible API breakages."""

    PARAMETER_MOVED = "Positional parameter was moved"
    """Positional parameter was moved"""
    PARAMETER_REMOVED = "Parameter was removed"
    """Parameter was removed"""
    PARAMETER_CHANGED_KIND = "Parameter kind was changed"
    """Parameter kind was changed"""
    PARAMETER_CHANGED_DEFAULT = "Parameter default was changed"
    """Parameter default was changed"""
    PARAMETER_CHANGED_REQUIRED = "Parameter is now required"
    """Parameter is now required"""
    PARAMETER_ADDED_REQUIRED = "Parameter was added as required"
    """Parameter was added as required"""
    RETURN_CHANGED_TYPE = "Return types are incompatible"
    """Return types are incompatible"""
    OBJECT_REMOVED = "Public object was removed"
    """Public object was removed"""
    OBJECT_CHANGED_KIND = "Public object points to a different kind of object"
    """Public object points to a different kind of object"""
    ATTRIBUTE_CHANGED_TYPE = "Attribute types are incompatible"
    """Attribute types are incompatible"""
    ATTRIBUTE_CHANGED_VALUE = "Attribute value was changed"
    """Attribute value was changed"""
    CLASS_REMOVED_BASE = "Base class was removed"
    """Base class was removed"""


class Parser(str, Enum):
    """Enumeration of the different docstring parsers."""

    auto = "auto"
    """Infer docstring parser."""
    google = "google"
    """Google-style docstrings parser."""
    sphinx = "sphinx"
    """Sphinx-style docstrings parser."""
    numpy = "numpy"
    """Numpydoc-style docstrings parser."""


class ObjectKind(str, Enum):
    """Enumeration of the different runtime object kinds."""

    MODULE = "module"
    """Modules."""
    CLASS = "class"
    """Classes."""
    STATICMETHOD = "staticmethod"
    """Static methods."""
    CLASSMETHOD = "classmethod"
    """Class methods."""
    METHOD_DESCRIPTOR = "method_descriptor"
    """Method descriptors."""
    METHOD = "method"
    """Methods."""
    BUILTIN_METHOD = "builtin_method"
    """Built-in methods."""
    COROUTINE = "coroutine"
    """Coroutines"""
    FUNCTION = "function"
    """Functions."""
    BUILTIN_FUNCTION = "builtin_function"
    """Built-in functions."""
    CACHED_PROPERTY = "cached_property"
    """Cached properties."""
    GETSET_DESCRIPTOR = "getset_descriptor"
    """Get/set descriptors."""
    PROPERTY = "property"
    """Properties."""
    TYPE_ALIAS = "type_alias"
    """Type aliases."""
    ATTRIBUTE = "attribute"
    """Attributes."""

    def __str__(self) -> str:
        return self.value
