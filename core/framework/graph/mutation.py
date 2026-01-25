from pydantic import BaseModel, Field
from typing import List, Dict, Any, Optional
from framework.graph.node import NodeSpec

class GraphDelta(BaseModel):
    """
    Represents a structural change to the graph.
    Used by the Evolutionary Memory system to request self-improvement.
    """
    reason: str
    source_memory_id: Optional[str] = None
    
    # Structural changes
    nodes_to_add: List[NodeSpec] = Field(default_factory=list)
    nodes_to_remove: List[str] = Field(default_factory=list)
    
    # Edge changes: source_id -> target_id
    edges_to_add: Dict[str, str] = Field(default_factory=dict)
    edges_to_remove: Dict[str, str] = Field(default_factory=dict)
    
    # Configuration updates: node_id -> new_config
    config_updates: Dict[str, Dict[str, Any]] = Field(default_factory=dict)
