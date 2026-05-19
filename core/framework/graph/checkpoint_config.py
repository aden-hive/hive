"""
Checkpoint Configuration - Controls checkpoint behavior during execution.
"""

from dataclasses import dataclass


@dataclass
class CheckpointConfig:
    """
    Configuration for checkpoint behavior during graph execution.

    Controls when checkpoints are created, how they're stored,
    and when they're pruned.
    """

    # Enable/disable checkpointing
    enabled: bool = True

    # When to checkpoint
    checkpoint_on_node_start: bool = True
    checkpoint_on_node_complete: bool = True

    # Pruning (time-based)
    checkpoint_max_age_days: int = 7  # Prune checkpoints older than 1 week
    prune_every_n_nodes: int = 10  # Check for pruning every N nodes

    # Performance
    async_checkpoint: bool = True  # Don't block execution on checkpoint writes

    # What to include in checkpoints
    include_full_memory: bool = True
    include_metrics: bool = True

    def should_checkpoint_node_start(self) -> bool:
        """Check if should checkpoint before node execution."""
        return self.enabled and self.checkpoint_on_node_start

    def should_checkpoint_node_complete(self) -> bool:
        """Check if should checkpoint after node execution."""
        return self.enabled and self.checkpoint_on_node_complete

    def should_prune_checkpoints(self, nodes_executed: int) -> bool:
        """
        Check if should prune checkpoints based on execution progress.

        Args:
            nodes_executed: Number of nodes executed so far

        Returns:
            True if should check for old checkpoints and prune them
        """
        return (
            self.enabled
            and self.prune_every_n_nodes > 0
            and nodes_executed % self.prune_every_n_nodes == 0
        )


# Default configuration for most agents
DEFAULT_CHECKPOINT_CONFIG = CheckpointConfig(
    enabled=True,
    checkpoint_on_node_start=True,
    checkpoint_on_node_complete=True,
    checkpoint_max_age_days=7,
    prune_every_n_nodes=10,
    async_checkpoint=True,
)


# Minimal configuration (only checkpoint at node completion)
MINIMAL_CHECKPOINT_CONFIG = CheckpointConfig(
    enabled=True,
    checkpoint_on_node_start=False,
    checkpoint_on_node_complete=True,
    checkpoint_max_age_days=7,
    prune_every_n_nodes=20,
    async_checkpoint=True,
)


# Disabled configuration (no checkpointing)
DISABLED_CHECKPOINT_CONFIG = CheckpointConfig(
    enabled=False,
)
