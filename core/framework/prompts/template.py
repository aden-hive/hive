"""Prompt registry for Hive framework."""

import random
import threading
import time
from typing import Dict, List, Optional, Tuple
from datetime import datetime
from .template import PromptTemplate


class PromptRegistry:
    """
    Central registry for prompt templates with versioning and A/B testing.
    
    Example (from issue #1131):
        >>> registry = PromptRegistry()
        >>> registry.register("judge.system", "You are a judge...", variables=["goal"])
        >>> prompt = registry.render("judge.system", {"goal": "Complete task"})
        >>> registry.add_variant("judge.system", "v2", "New prompt...", weight=0.2)
        >>> registry.record_outcome("judge.system", success=True, latency_ms=150)
        >>> print(registry.get_stats("judge.system"))
    """
    
    def __init__(self):
        self._templates: Dict[str, PromptTemplate] = {}
        self._variants: Dict[str, List[Tuple[PromptTemplate, float]]] = {}
        self._outcomes: List[Dict] = []
        self._lock = threading.Lock()
    
    def register(self, template_id: str, content: str, variables: Optional[List[str]] = None) -> None:
        """
        Register a new prompt template.
        
        Args:
            template_id: Unique identifier (e.g., "judge.system")
            content: Prompt text with {variable} placeholders
            variables: Optional list of variable names
            
        Example:
            registry.register("greeting", "Hello {name}!", ["name"])
        """
        with self._lock:
            if template_id in self._templates:
                raise ValueError(f"Template '{template_id}' already exists")
            
            template = PromptTemplate(
                id=template_id,
                content=content,
                variables=variables or []
            )
            self._templates[template_id] = template
            self._variants[template_id] = []
    
    def add_variant(self, template_id: str, version: str, content: str, weight: float = 1.0) -> None:
        """
        Add a variant for A/B testing.
        
        Args:
            template_id: Base template ID
            version: Variant version (e.g., "v2")
            content: Variant prompt content
            weight: Selection weight (default: 1.0)
            
        Example:
            registry.add_variant("greeting", "v2", "Hi {name}!", weight=0.2)
        """
        with self._lock:
            if template_id not in self._templates:
                raise ValueError(f"Template '{template_id}' not found")
            
            # Create variant template
            variant_template = PromptTemplate(
                id=f"{template_id}@{version}",
                content=content,
                variables=self._templates[template_id].variables,
                version=version
            )
            
            # Add to variants list
            self._variants[template_id].append((variant_template, weight))
    
    def _select_template(self, template_id: str) -> PromptTemplate:
        """Select template or variant based on A/B weights."""
        variants = self._variants.get(template_id, [])
        
        if not variants:
            return self._templates[template_id]
        
        # Weighted random selection
        templates, weights = zip(*variants)
        return random.choices(templates, weights=weights, k=1)[0]
    
    def render(self, template_id: str, context: Dict[str, str]) -> str:
        """
        Render a template with context.
        
        Args:
            template_id: Template ID to render
            context: Variable values for substitution
            
        Returns:
            Rendered prompt string
        """
        start_time = time.perf_counter()
        
        try:
            with self._lock:
                template = self._select_template(template_id)
            
            result = template.render(context)
            
            latency_ms = (time.perf_counter() - start_time) * 1000
            self.record_outcome(
                template_id=template_id,
                success=True,
                latency_ms=latency_ms
            )
            
            return result
            
        except Exception as e:
            latency_ms = (time.perf_counter() - start_time) * 1000
            self.record_outcome(
                template_id=template_id,
                success=False,
                latency_ms=latency_ms
            )
            raise
    
    def record_outcome(self, template_id: str, success: bool, latency_ms: float) -> None:
        """Record performance metrics."""
        outcome = {
            "template_id": template_id,
            "success": success,
            "latency_ms": latency_ms,
            "timestamp": datetime.now()
        }
        
        with self._lock:
            self._outcomes.append(outcome)
    
    def get_stats(self, template_id: Optional[str] = None) -> Dict:
        """
        Get performance statistics.
        
        Args:
            template_id: Optional template ID to filter by
            
        Returns:
            Statistics dictionary
        """
        with self._lock:
            if template_id:
                outcomes = [o for o in self._outcomes if o["template_id"] == template_id]
            else:
                outcomes = self._outcomes
            
            if not outcomes:
                return {
                    "total_renders": 0,
                    "success_rate": 0.0,
                    "avg_latency_ms": 0.0
                }
            
            total = len(outcomes)
            successful = sum(1 for o in outcomes if o["success"])
            latencies = [o["latency_ms"] for o in outcomes]
            
            return {
                "total_renders": total,
                "success_rate": successful / total,
                "avg_latency_ms": sum(latencies) / total
            }