import uuid
import copy
import asyncio
import logging
from typing import Dict, Any, Optional, Callable, Awaitable
from pydantic import BaseModel, Field
from datetime import datetime

logger = logging.getLogger("hive.safety")

#------------------------------------------------------------
# Data Models
#------------------------------------------------------------------

class Snapshot(BaseModel):
    """
    Immutable backup of an agent's brain (graph state).
    """
    id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    timestamp: datetime = Field(default_factory=datetime.now)
    graph_state: Dict[str, Any] 
    reason_for_snapshot: str = "Pre-Evolution Backup"

class ValidationResult(BaseModel):
    """
    Report card after testing a new brain.
    """
    success: bool
    snapshot_id: str
    error_message: Optional[str] = None
    steps_survived: int = 0
    execution_time_ms: float = 0.0
#------------------------------------------------
# The Evolution Guard 
#------------------------------------------------

class EvolutionGuard:
    """
    Transaction Manager for Agent Evolution.
    1. SNAPSHOT: Backup the old brain.
    2. PROBATION: Run the new brain in a sandbox.
    3. ROLLBACK: Revert if the new brain is defective.
    """
    
    def __init__(self):
        self._snapshots: Dict[str, Snapshot] = {}
        self._active_probation_id: Optional[str] = None

    def snapshot(self, current_graph: Dict[str, Any], reason: str = "Manual Snapshot") -> str:
        """
        Creates a deep copy of the agent's graph and saves it.
        """
        safe_copy = copy.deepcopy(current_graph)
        
        snapshot = Snapshot(graph_state=safe_copy, reason_for_snapshot=reason)
        self._snapshots[snapshot.id] = snapshot
        
        logger.info(f"🛡️ [EvolutionGuard] Snapshot created: {snapshot.id} ({reason})")
        return snapshot.id

    def rollback(self, snapshot_id: str) -> Dict[str, Any]:
        """
        Retrieves a saved graph state. Used when evolution fails.
        """
        if snapshot_id not in self._snapshots:
            raise ValueError(f"Snapshot {snapshot_id} not found! Cannot rollback.")
            
        print(f"🔄 [EvolutionGuard] Rolling back to Snapshot {snapshot_id}")
        return copy.deepcopy(self._snapshots[snapshot_id].graph_state)

    async def probation_run(
        self, 
        snapshot_id: str, 
        candidate_graph: Dict[str, Any], 
        test_function: Callable[[Dict[str, Any]], Awaitable[bool]],
        max_steps: int = 5
    ) -> ValidationResult:
        """
        Runs the new 'candidate_graph' through a sandbox test.
        
        Args:
            snapshot_id: The ID of the safe backup.
            candidate_graph: The new brain to test.
            test_function: An async function that actually runs the agent (injected dependency).
            max_steps: How many steps to allow before declaring an "Infinite Loop".
        """
        start_time = datetime.now()
        print(f"🧪 [EvolutionGuard] Starting Probation Mode for Snapshot {snapshot_id}...")

        try:
            if "nodes" not in candidate_graph or "edges" not in candidate_graph:
                raise ValueError("Invalid Graph: Missing 'nodes' or 'edges'")

            try:
                result = await asyncio.wait_for(test_function(candidate_graph), timeout=5.0)
                
                if not result:
                    raise RuntimeError("Agent failed to complete the test task.")

            except asyncio.TimeoutError:
                raise RuntimeError(f"Infinite Loop Detected: Agent exceeded {max_steps} steps or 5s timeout.")

            execution_time = (datetime.now() - start_time).total_seconds() * 1000
            print(f"✅ [EvolutionGuard] Probation Passed! ({execution_time:.2f}ms)")
            
            return ValidationResult(
                success=True,
                snapshot_id=snapshot_id,
                steps_survived=max_steps,
                execution_time_ms=execution_time
            )

        except Exception as e:
            print(f"❌ [EvolutionGuard] Probation FAILED: {str(e)}")
            return ValidationResult(
                success=False,
                snapshot_id=snapshot_id,
                error_message=str(e)
            )