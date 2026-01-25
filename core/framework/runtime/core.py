"""
Runtime Core - The interface agents use to record their behavior.

This is designed to make it EASY for agents to record decisions in a way
that Builder can analyze. The agent calls simple methods, and the runtime
handles all the structured logging.

Performance Optimized (v0.2.0):
- Fully async operations
- Async storage backends
- Non-blocking I/O
"""

import asyncio
import logging
import uuid
from datetime import datetime
from pathlib import Path
from typing import Any, Callable, Optional

from framework.schemas.decision import Decision, Option, Outcome, DecisionType
from framework.schemas.run import Run, RunStatus
from framework.storage.async_backend import StorageFactory, StorageBackend

logger = logging.getLogger(__name__)


class Runtime:
    """
    The runtime environment that agents execute within.
    
    Async implementation for high-performance decision recording.
    
    Usage:
        runtime = Runtime("/path/to/storage")
        await runtime.initialize()
        
        # Start a run
        run_id = await runtime.start_run("goal_123", "Qualify sales leads")
        
        # Record a decision
        decision_id = await runtime.decide(
            node_id="lead-qualifier",
            intent="Determine if lead has budget",
            options=[...],
            chosen="infer",
            reasoning="..."
        )
        
        # Record the outcome
        await runtime.record_outcome(
            decision_id=decision_id,
            success=True,
            result=...
        )
        
        # End the run
        await runtime.end_run(success=True)
    """
    
    def __init__(
        self,
        storage_path: str | Path,
        storage_backend: str = "file",
        storage_kwargs: Optional[dict] = None
    ):
        self.storage_path = Path(storage_path)
        self.storage_backend_type = storage_backend
        self.storage_kwargs = storage_kwargs or {}
        
        # Storage initialization deferred to initialize()
        self.storage: Optional[StorageBackend] = None
        
        self._current_run: Run | None = None
        self._current_node: str = "unknown"
        self._lock = asyncio.Lock()
    
    async def initialize(self) -> None:
        """Initialize storage backend."""
        if self.storage is None:
            # Add base_path to kwargs for file storage
            kwargs = self.storage_kwargs.copy()
            if self.storage_backend_type == "file" and "base_path" not in kwargs:
                kwargs["base_path"] = self.storage_path
            
            self.storage = StorageFactory.create(
                self.storage_backend_type,
                **kwargs
            )
    
    # === RUN LIFECYCLE ===
    
    async def start_run(
        self,
        goal_id: str,
        goal_description: str = "",
        input_data: dict[str, Any] | None = None,
    ) -> str:
        """Start a new run asynchronously."""
        if self.storage is None:
            await self.initialize()
        
        run_id = f"run_{datetime.now().strftime('%Y%m%d_%H%M%S')}_{uuid.uuid4().hex[:8]}"
        
        async with self._lock:
            self._current_run = Run(
                id=run_id,
                goal_id=goal_id,
                goal_description=goal_description,
                input_data=input_data or {},
            )
            
            # Save initial run state
            if self.storage:
                await self.storage.save_run(self._current_run)
        
        return run_id
    
    async def end_run(
        self,
        success: bool,
        narrative: str = "",
        output_data: dict[str, Any] | None = None,
    ) -> None:
        """End the current run asynchronously."""
        async with self._lock:
            if self._current_run is None:
                logger.warning("end_run called but no run in progress")
                return
            
            status = RunStatus.COMPLETED if success else RunStatus.FAILED
            self._current_run.output_data = output_data or {}
            self._current_run.complete(status, narrative)
            
            if self.storage:
                await self.storage.save_run(self._current_run)
                
            self._current_run = None
    
    def set_node(self, node_id: str) -> None:
        """Set current node (sync, in-memory only)."""
        self._current_node = node_id
    
    @property
    def current_run(self) -> Run | None:
        return self._current_run
    
    # === DECISION RECORDING ===
    
    async def decide(
        self,
        intent: str,
        options: list[dict[str, Any]],
        chosen: str,
        reasoning: str,
        node_id: str | None = None,
        decision_type: DecisionType = DecisionType.CUSTOM,
        constraints: list[str] | None = None,
        context: dict[str, Any] | None = None,
    ) -> str:
        """Record a decision asynchronously."""
        async with self._lock:
            if self._current_run is None:
                logger.warning(f"decide called but no run: {intent}")
                return ""
            
            # Build Option objects
            option_objects = []
            for opt in options:
                option_objects.append(Option(
                    id=opt["id"],
                    description=opt.get("description", ""),
                    action_type=opt.get("action_type", "unknown"),
                    action_params=opt.get("action_params", {}),
                    pros=opt.get("pros", []),
                    cons=opt.get("cons", []),
                    confidence=opt.get("confidence", 0.5),
                ))
            
            decision_id = f"dec_{len(self._current_run.decisions)}"
            decision = Decision(
                id=decision_id,
                node_id=node_id or self._current_node,
                intent=intent,
                decision_type=decision_type,
                options=option_objects,
                chosen_option_id=chosen,
                reasoning=reasoning,
                active_constraints=constraints or [],
                input_context=context or {},
            )
            
            self._current_run.add_decision(decision)
            
            if self.storage:
                await self.storage.save_run(self._current_run)
            
            return decision_id
    
    async def record_outcome(
        self,
        decision_id: str,
        success: bool,
        result: Any = None,
        error: str | None = None,
        summary: str = "",
        state_changes: dict[str, Any] | None = None,
        tokens_used: int = 0,
        latency_ms: int = 0,
    ) -> None:
        """Record outcome asynchronously."""
        async with self._lock:
            if self._current_run is None:
                logger.warning(f"record_outcome called but no run: {decision_id}")
                return
            
            outcome = Outcome(
                success=success,
                result=result,
                error=error,
                summary=summary,
                state_changes=state_changes or {},
                tokens_used=tokens_used,
                latency_ms=latency_ms,
            )
            
            self._current_run.record_outcome(decision_id, outcome)
            
            if self.storage:
                await self.storage.save_run(self._current_run)
    
    async def report_problem(
        self,
        severity: str,
        description: str,
        decision_id: str | None = None,
        root_cause: str | None = None,
        suggested_fix: str | None = None,
    ) -> str:
        """Report problem asynchronously."""
        async with self._lock:
            if self._current_run is None:
                logger.warning(f"report_problem called but no run: {description}")
                return ""
            
            problem_id = self._current_run.add_problem(
                severity=severity,
                description=description,
                decision_id=decision_id,
                root_cause=root_cause,
                suggested_fix=suggested_fix,
            )
            
            if self.storage:
                await self.storage.save_run(self._current_run)
                
            return problem_id
    
    # === CONVENIENCE METHODS ===
    
    async def decide_and_execute(
        self,
        intent: str,
        options: list[dict[str, Any]],
        chosen: str,
        reasoning: str,
        executor: Callable,
        **kwargs,
    ) -> tuple[str, Any]:
        """Record decision and execute asynchronously."""
        import time
        
        decision_id = await self.decide(
            intent=intent,
            options=options,
            chosen=chosen,
            reasoning=reasoning,
            **kwargs,
        )
        
        start = time.time()
        try:
            if asyncio.iscoroutinefunction(executor):
                result = await executor()
            else:
                result = executor()
            
            latency_ms = int((time.time() - start) * 1000)
            
            await self.record_outcome(
                decision_id=decision_id,
                success=True,
                result=result,
                latency_ms=latency_ms,
            )
            return decision_id, result
            
        except Exception as e:
            latency_ms = int((time.time() - start) * 1000)
            
            await self.record_outcome(
                decision_id=decision_id,
                success=False,
                error=str(e),
                latency_ms=latency_ms,
            )
            raise
    
    async def quick_decision(
        self,
        intent: str,
        action: str,
        reasoning: str,
        node_id: str | None = None,
    ) -> str:
        """Record quick decision asynchronously."""
        return await self.decide(
            intent=intent,
            options=[{
                "id": "action",
                "description": action,
                "action_type": "execute",
            }],
            chosen="action",
            reasoning=reasoning,
            node_id=node_id,
        )
    
    async def close(self) -> None:
        """Close storage connection."""
        if self.storage:
            await self.storage.close()
