"""Tests for PromptRegistry."""

import pytest
from core.framework.prompts import PromptRegistry, TemplateNotFoundError, MissingContextError


def test_register_and_render():
    """Basic registration and rendering."""
    registry = PromptRegistry()
    
    # Register a template
    registry.register("greeting", "Hello {name}!", ["name"])
    
    # Render with context
    result = registry.render("greeting", {"name": "World"})
    assert result == "Hello World!"
    
    # Test missing variable
    with pytest.raises(MissingContextError):
        registry.render("greeting", {})


def test_template_not_found():
    """Error when template doesn't exist."""
    registry = PromptRegistry()
    with pytest.raises(TemplateNotFoundError):
        registry.render("nonexistent", {})


def test_add_variant():
    """A/B testing variants."""
    registry = PromptRegistry()
    registry.register("test", "Base {var}", ["var"])
    registry.add_variant("test", "v2", "Variant {var}", weight=0.5)
    
    # Should render something (random, so can't assert exact value)
    result = registry.render("test", {"var": "x"})
    assert "x" in result  # Should contain the variable value


def test_record_outcome_and_stats():
    """Performance tracking."""
    registry = PromptRegistry()
    registry.register("test", "Hello", [])
    
    # Record some outcomes
    registry.record_outcome("test", True, 100.0)
    registry.record_outcome("test", False, 200.0)
    
    stats = registry.get_stats("test")
    assert stats["total_renders"] == 2
    assert stats["success_rate"] == 0.5
    assert stats["avg_latency_ms"] == 150.0


def test_duplicate_registration():
    """Cannot register same ID twice."""
    registry = PromptRegistry()
    registry.register("test", "Content")
    
    with pytest.raises(ValueError, match="already exists"):
        registry.register("test", "Different content")