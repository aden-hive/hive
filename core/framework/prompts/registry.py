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
    """
    
    def __init__(self):
        self._templates: Dict[str, PromptTemplate] = {}
        self._variants: Dict[str, List[Tuple[PromptTemplate, float]]] = {}
        self._outcomes: List[Dict] = []
        self._lock = threading.Lock()
    
    def register(self, template_id: str, content: str, variables: Optional[List[str]] = None) -> None:
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
        with self._lock:
            if template_id not in self._templates:
                raise ValueError(f"Template '{template_id}' not found")
            
            variant_template = PromptTemplate(
                id=f"{template_id}@{version}",
                content=content,
                variables=self._templates[template_id].variables,
                version=version
            )
            self._variants[template_id].append((variant_template, weight))
    
    def _select_template(self, template_id: str) -> PromptTemplate:
        variants = self._variants.get(template_id, [])
        if not variants:
            return self._templates[template_id]
        
        templates, weights = zip(*variants)
        return random.choices(templates, weights=weights, k=1)[0]
    
    def render(self, template_id: str, context: Dict[str, str]) -> str:
        start_time = time.perf_counter()
        
        try:
            with self._lock:
                template = self._select_template(template_id)
            
            result = template.render(context)
            
            latency_ms = (time.perf_counter() - start_time) * 1000
            self.record_outcome(template_id, True, latency_ms)
            return result
            
        except Exception as e:
            latency_ms = (time.perf_counter() - start_time) * 1000
            self.record_outcome(template_id, False, latency_ms)
            raise
    
    def record_outcome(self, template_id: str, success: bool, latency_ms: float) -> None:
        outcome = {
            "template_id": template_id,
            "success": success,
            "latency_ms": latency_ms,
            "timestamp": datetime.now()
        }
        with self._lock:
            self._outcomes.append(outcome)
    
    def get_stats(self, template_id: Optional[str] = None) -> Dict:
        with self._lock:
            if template_id:
                outcomes = [o for o in self._outcomes if o["template_id"] == template_id]
            else:
                outcomes = self._outcomes
            
            if not outcomes:
                return {"total_renders": 0, "success_rate": 0.0, "avg_latency_ms": 0.0}
            
            total = len(outcomes)
            successful = sum(1 for o in outcomes if o["success"])
            latencies = [o["latency_ms"] for o in outcomes]
            
            return {
                "total_renders": total,
                "success_rate": successful / total,
                "avg_latency_ms": sum(latencies) / total
            }