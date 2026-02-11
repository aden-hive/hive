# Resumable Sessions Design

## Problem Statement

Currently, when an agent encounters a failure during execution (e.g., credential validation, API errors, tool failures), the entire session is lost. This creates a poor user experience, especially when:

1. The agent has completed significant work before the failure
2. The failure is recoverable (e.g., adding missing credentials)
3. The user wants to retry from the exact failure point without redoing work

## Design Goals

1. **Crash Recovery**: Sessions can resume after process crashes or errors
2. **Partial Completion**: Preserve work done by nodes that completed successfully
3. **Flexible Resume Points**: Resume from exact failure point or previous checkpoints
4. **State Consistency**: Guarantee consistent SharedMemory and conversation state
5. **Minimal Overhead**: Checkpointing shouldn't significantly impact performance
6. **User Control**: Users can inspect, modify, and resume sessions explicitly

## Architecture

### 1. Checkpoint System

#### Checkpoint Types

**Automatic Checkpoints** (saved automatically by framework):
- `node_start`: Before each node begins execution
- `node_complete`: After each node successfully completes
- `edge_transition`: Before traversing to next node
- `loop_iteration`: At each iteration in EventLoopNode (optional)

**Manual Checkpoints** (triggered by agent designer):
- `safe_point`: Explicitly marked safe points in graph
- `user_checkpoint`: Before awaiting user input in client-facing nodes

#### Checkpoint Data Structure

```python
@dataclass
class Checkpoint:
    """Single checkpoint in execution timeline."""

    # Identity
    checkpoint_id: str  # Format: checkpoint_{timestamp}_{uuid_short}
    session_id: str
    checkpoint_type: str  # "node_start", "node_complete", etc.

    # Timestamps
    created_at: str  # ISO 8601

    # Execution state
    current_node: str | None
    next_node: str | None  # For edge_transition checkpoints
    execution_path: list[str]  # Nodes executed so far

    # Memory state (snapshot)
    shared_memory: dict[str, Any]  # Full SharedMemory._data

    # Per-node conversation state references
    # (actual conversations stored separately, reference by node_id)
    conversation_states: dict[str, str]  # {node_id: conversation_checkpoint_id}

    # Output accumulator state
    accumulated_outputs: dict[str, Any]

    # Execution metrics (for resuming quality tracking)
    metrics_snapshot: dict[str, Any]

    # Metadata
    is_clean: bool  # True if no failures/retries before this checkpoint
    can_resume_from: bool  # False if checkpoint is in unstable state
    description: str  # Human-readable checkpoint description
```

#### Storage Structure

```
~/.hive/agents/{agent_name}/
└── sessions/
    └── session_YYYYMMDD_HHMMSS_{uuid}/
        ├── state.json                    # Session state (existing)
        ├── checkpoints/
        │   ├── index.json                # Checkpoint index/manifest
        │   ├── checkpoint_1.json         # Individual checkpoints
        │   ├── checkpoint_2.json
        │   └── checkpoint_N.json
        ├── conversations/                # Per-node conversation state (existing)
        │   ├── node_id_1/
        │   │   ├── parts/
        │   │   ├── meta.json
        │   │   └── cursor.json
        │   └── node_id_2/...
        ├── data/                         # Spillover artifacts (existing)
        └── logs/                         # L1/L2/L3 logs (existing)
```

**Checkpoint Index Format** (`checkpoints/index.json`):
```json
{
  "session_id": "session_20260208_143022_abc12345",
  "checkpoints": [
    {
      "checkpoint_id": "checkpoint_20260208_143030_xyz123",
      "type": "node_complete",
      "created_at": "2026-02-08T14:30:30.123Z",
      "current_node": "collector",
      "is_clean": true,
      "can_resume_from": true,
      "description": "Completed collector node successfully"
    },
    {
      "checkpoint_id": "checkpoint_20260208_143045_abc789",
      "type": "node_start",
      "created_at": "2026-02-08T14:30:45.456Z",
      "current_node": "analyzer",
      "is_clean": true,
      "can_resume_from": true,
      "description": "Starting analyzer node"
    }
  ],
  "latest_checkpoint_id": "checkpoint_20260208_143045_abc789",
  "total_checkpoints": 2
}
```

### 2. Resume Mechanism

#### Resume Flow

```python
# High-level resume flow
async def resume_session(
    session_id: str,
    checkpoint_id: str | None = None,  # None = resume from latest
    modifications: dict[str, Any] | None = None,  # Override memory values
) -> ExecutionResult:
    """
    Resume a session from a checkpoint.

    Args:
        session_id: Session to resume
        checkpoint_id: Specific checkpoint (None = latest)
        modifications: Optional memory/state modifications before resume

    Returns:
        ExecutionResult with resumed execution
    """
    # 1. Load session state
    session_state = await session_store.read_state(session_id)

    # 2. Verify session is resumable
    if not session_state.is_resumable:
        raise ValueError(f"Session {session_id} is not resumable")

    # 3. Load checkpoint
    checkpoint = await checkpoint_store.load_checkpoint(
        session_id,
        checkpoint_id or session_state.progress.resume_from
    )

    # 4. Restore state
    # - Restore SharedMemory from checkpoint.shared_memory
    # - Restore per-node conversations from checkpoint.conversation_states
    # - Restore output accumulator from checkpoint.accumulated_outputs
    # - Apply modifications if provided

    # 5. Resume execution from checkpoint.next_node or checkpoint.current_node
    result = await executor.execute(
        graph=graph,
        goal=goal,
        memory=restored_memory,
        entry_point=checkpoint.next_node or checkpoint.current_node,
        session_state=restored_session_state,
    )

    # 6. Update session state with resumed execution
    await session_store.write_state(session_id, updated_state)

    return result
```

#### Checkpoint Restoration

```python
@dataclass
class CheckpointStore:
    """Manages checkpoint storage and retrieval."""

    async def save_checkpoint(
        self,
        session_id: str,
        checkpoint: Checkpoint,
    ) -> None:
        """Save a checkpoint atomically."""
        # 1. Write checkpoint file: checkpoints/checkpoint_{id}.json
        # 2. Update index: checkpoints/index.json
        # 3. Use atomic write for crash safety

    async def load_checkpoint(
        self,
        session_id: str,
        checkpoint_id: str | None = None,
    ) -> Checkpoint | None:
        """Load a checkpoint by ID or latest."""
        # 1. Read checkpoint index
        # 2. Find checkpoint by ID (or latest if None)
        # 3. Load and deserialize checkpoint file

    async def list_checkpoints(
        self,
        session_id: str,
        checkpoint_type: str | None = None,
        is_clean: bool | None = None,
    ) -> list[Checkpoint]:
        """List all checkpoints for a session with optional filters."""

    async def delete_checkpoint(
        self,
        session_id: str,
        checkpoint_id: str,
    ) -> bool:
        """Delete a specific checkpoint."""

    async def prune_checkpoints(
        self,
        session_id: str,
        keep_count: int = 10,
        keep_clean_only: bool = False,
    ) -> int:
        """Prune old checkpoints, keeping most recent N."""
```

### 3. GraphExecutor Integration

#### Modified Execution Loop

```python
# In GraphExecutor.execute()

async def execute(
    self,
    graph: GraphSpec,
    goal: Goal,
    memory: SharedMemory | None = None,
    entry_point: str = "start",
    session_state: dict[str, Any] | None = None,
    checkpoint_config: CheckpointConfig | None = None,
) -> ExecutionResult:
    """
    Execute graph with checkpointing support.

    New parameters:
        checkpoint_config: Configuration for checkpointing behavior
    """

    # Initialize checkpoint store
    checkpoint_store = CheckpointStore(storage_path / "checkpoints")

    # Restore from checkpoint if session_state indicates resume
    if session_state and session_state.get("resume_from"):
        checkpoint = await checkpoint_store.load_checkpoint(
            session_id,
            session_state["resume_from"]
        )
        memory = self._restore_memory_from_checkpoint(checkpoint)
        entry_point = checkpoint.next_node or checkpoint.current_node

    current_node = entry_point

    while current_node:
        # CHECKPOINT: node_start
        if checkpoint_config and checkpoint_config.checkpoint_on_node_start:
            await self._save_checkpoint(
                checkpoint_store,
                checkpoint_type="node_start",
                current_node=current_node,
                memory=memory,
                # ... other state
            )

        try:
            # Execute node
            result = await self._execute_node(current_node, memory, context)

            # CHECKPOINT: node_complete
            if checkpoint_config and checkpoint_config.checkpoint_on_node_complete:
                await self._save_checkpoint(
                    checkpoint_store,
                    checkpoint_type="node_complete",
                    current_node=current_node,
                    memory=memory,
                    # ... other state
                )

        except Exception as e:
            # On failure, mark current checkpoint as resume point
            await self._mark_failure_checkpoint(
                checkpoint_store,
                current_node=current_node,
                error=str(e),
            )
            raise

        # Find next edge
        next_node = self._find_next_node(current_node, result, memory)

        # CHECKPOINT: edge_transition
        if next_node and checkpoint_config and checkpoint_config.checkpoint_on_edge:
            await self._save_checkpoint(
                checkpoint_store,
                checkpoint_type="edge_transition",
                current_node=current_node,
                next_node=next_node,
                memory=memory,
                # ... other state
            )

        current_node = next_node
```

### 4. EventLoopNode Integration

#### Conversation State Checkpointing

EventLoopNode already has conversation persistence via `ConversationStore`. For resumability:

```python
class EventLoopNode:
    async def execute(self, ctx: NodeContext) -> NodeResult:
        """Execute with checkpoint support."""

        # Try to restore from checkpoint
        if ctx.checkpoint_id:
            conversation = await self._restore_conversation(ctx.checkpoint_id)
            output_accumulator = await OutputAccumulator.restore(self.store)
        else:
            # Fresh start
            conversation = await self._initialize_conversation(ctx)
            output_accumulator = OutputAccumulator(store=self.store)

        # Event loop with periodic checkpointing
        iteration = 0
        while iteration < self.config.max_iterations:

            # Optional: checkpoint every N iterations
            if self.config.checkpoint_every_n_iterations:
                if iteration % self.config.checkpoint_every_n_iterations == 0:
                    await self._save_loop_checkpoint(
                        conversation,
                        output_accumulator,
                        iteration,
                    )

            # ... rest of event loop

            iteration += 1
```

**Note**: EventLoopNode conversation state is already persisted to disk after each turn via `ConversationStore`, so it's naturally resumable. We just need to:
1. Track which conversation checkpoint to restore from
2. Ensure output accumulator state is also restored

### 5. User-Facing API

#### MCP Tools for Resume

```python
# In tools/src/aden_tools/tools/session_management/

@tool
async def list_resumable_sessions(
    agent_work_dir: str,
    status: str = "failed",  # "failed", "paused", "cancelled"
    limit: int = 20,
) -> dict:
    """
    List sessions that can be resumed.

    Returns:
        {
            "sessions": [
                {
                    "session_id": "session_20260208_143022_abc12345",
                    "status": "failed",
                    "error": "Missing API key: OPENAI_API_KEY",
                    "failed_at_node": "analyzer",
                    "last_checkpoint": "checkpoint_20260208_143045_abc789",
                    "created_at": "2026-02-08T14:30:22Z",
                    "updated_at": "2026-02-08T14:30:45Z"
                }
            ],
            "total": 1
        }
    """

@tool
async def list_session_checkpoints(
    agent_work_dir: str,
    session_id: str,
    checkpoint_type: str = "",  # Filter by type
    clean_only: bool = False,  # Only show clean checkpoints
) -> dict:
    """
    List all checkpoints for a session.

    Returns:
        {
            "session_id": "session_20260208_143022_abc12345",
            "checkpoints": [
                {
                    "checkpoint_id": "checkpoint_20260208_143030_xyz123",
                    "type": "node_complete",
                    "created_at": "2026-02-08T14:30:30Z",
                    "current_node": "collector",
                    "is_clean": true,
                    "can_resume_from": true,
                    "description": "Completed collector node successfully"
                },
                ...
            ]
        }
    """

@tool
async def inspect_checkpoint(
    agent_work_dir: str,
    session_id: str,
    checkpoint_id: str,
    include_memory: bool = False,  # Include full memory state
) -> dict:
    """
    Inspect a checkpoint's detailed state.

    Returns:
        {
            "checkpoint_id": "checkpoint_20260208_143030_xyz123",
            "type": "node_complete",
            "current_node": "collector",
            "execution_path": ["start", "collector"],
            "accumulated_outputs": {
                "twitter_handles": ["@user1", "@user2"]
            },
            "memory": {...},  # If include_memory=True
            "metrics_snapshot": {
                "total_retries": 2,
                "nodes_with_failures": []
            }
        }
    """

@tool
async def resume_session(
    agent_work_dir: str,
    session_id: str,
    checkpoint_id: str = "",  # Empty = latest checkpoint
    memory_modifications: str = "{}",  # JSON string of memory overrides
) -> dict:
    """
    Resume a session from a checkpoint.

    Args:
        agent_work_dir: Path to agent workspace
        session_id: Session to resume
        checkpoint_id: Specific checkpoint (empty = latest)
        memory_modifications: JSON object with memory key overrides

    Returns:
        {
            "session_id": "session_20260208_143022_abc12345",
            "resumed_from": "checkpoint_20260208_143045_abc789",
            "status": "active",  # Now actively running
            "message": "Session resumed successfully from checkpoint_20260208_143045_abc789"
        }
    """
```

#### CLI Commands

```bash
# List resumable sessions
hive sessions list --agent deep_research_agent --status failed

# Show checkpoints for a session
hive sessions checkpoints session_20260208_143022_abc12345

# Inspect a checkpoint
hive sessions inspect session_20260208_143022_abc12345 checkpoint_20260208_143045_abc789

# Resume a session
hive sessions resume session_20260208_143022_abc12345

# Resume from specific checkpoint
hive sessions resume session_20260208_143022_abc12345 --checkpoint checkpoint_20260208_143030_xyz123

# Resume with memory modifications (e.g., after adding credentials)
hive sessions resume session_20260208_143022_abc12345 --set api_key=sk-...
```

### 6. Configuration

#### CheckpointConfig

```python
@dataclass
class CheckpointConfig:
    """Configuration for checkpoint behavior."""

    # When to checkpoint
    checkpoint_on_node_start: bool = True
    checkpoint_on_node_complete: bool = True
    checkpoint_on_edge: bool = False  # Usually redundant with node_start
    checkpoint_on_loop_iteration: bool = False  # Can be expensive
    checkpoint_every_n_iterations: int = 0  # 0 = disabled

    # Pruning
    max_checkpoints_per_session: int = 100
    prune_after_node_count: int = 10  # Prune every N nodes
    keep_clean_checkpoints_only: bool = False

    # Performance
    async_checkpoint: bool = True  # Don't block execution on checkpoint writes

    # What to include
    include_conversation_snapshots: bool = True
    include_full_memory: bool = True
```

#### Agent-Level Configuration

```python
# In agent.py or config.py

class MyAgent(Agent):
    def get_checkpoint_config(self) -> CheckpointConfig:
        """Override to customize checkpoint behavior."""
        return CheckpointConfig(
            checkpoint_on_node_start=True,
            checkpoint_on_node_complete=True,
            checkpoint_every_n_iterations=5,  # Checkpoint every 5 iterations in loops
            max_checkpoints_per_session=50,
        )
```

## Implementation Plan

### Phase 1: Core Checkpoint Infrastructure (Week 1)

1. **Create checkpoint schemas**
   - `Checkpoint` dataclass
   - `CheckpointIndex` for manifest
   - Serialization/deserialization

2. **Implement CheckpointStore**
   - `save_checkpoint()` with atomic writes
   - `load_checkpoint()` with deserialization
   - `list_checkpoints()` with filtering
   - `prune_checkpoints()` for cleanup

3. **Update SessionState schema**
   - Add `resume_from_checkpoint_id` field
   - Add `checkpoints_enabled` flag

### Phase 2: GraphExecutor Integration (Week 2)

1. **Modify GraphExecutor**
   - Add `CheckpointConfig` parameter
   - Implement checkpoint saving at node boundaries
   - Implement checkpoint restoration logic
   - Handle memory state snapshots

2. **Update execution loop**
   - Checkpoint before node execution
   - Checkpoint after successful completion
   - Mark failure checkpoints on errors

### Phase 3: EventLoopNode Integration (Week 3)

1. **Enhance conversation restoration**
   - Link checkpoints to conversation states
   - Ensure OutputAccumulator is checkpointed
   - Test loop resumption from middle of execution

2. **Add optional loop iteration checkpoints**
   - Configurable iteration frequency
   - Balance between granularity and performance

### Phase 4: User-Facing Features (Week 4)

1. **Implement MCP tools**
   - `list_resumable_sessions`
   - `list_session_checkpoints`
   - `inspect_checkpoint`
   - `resume_session`

2. **Add CLI commands**
   - `hive sessions list`
   - `hive sessions checkpoints`
   - `hive sessions inspect`
   - `hive sessions resume`

3. **Update TUI**
   - Show resumable sessions in UI
   - Allow resume from TUI interface

### Phase 5: Testing & Documentation (Week 5)

1. **Write comprehensive tests**
   - Unit tests for CheckpointStore
   - Integration tests for resume flow
   - Edge case testing (concurrent checkpoints, corruption, etc.)

2. **Performance testing**
   - Measure checkpoint overhead
   - Optimize async checkpoint writing
   - Test with large memory states

3. **Documentation**
   - Update skills with resume patterns
   - Document checkpoint configuration
   - Add troubleshooting guide

## Performance Considerations

### Checkpoint Overhead

**Estimated overhead per checkpoint**:
- Memory serialization: ~5-10ms for typical state (< 1MB)
- File I/O: ~10-20ms for atomic write
- Total: ~15-30ms per checkpoint

**Mitigation strategies**:
1. **Async checkpointing**: Don't block execution on writes
2. **Selective checkpointing**: Only checkpoint at important boundaries
3. **Incremental checkpoints**: Store deltas instead of full state (future)
4. **Compression**: Compress large memory states before writing

### Storage Size

**Typical checkpoint size**:
- Small memory state (< 100KB): ~50-100KB per checkpoint
- Medium memory state (< 1MB): ~500KB-1MB per checkpoint
- Large memory state (> 1MB): ~1-5MB per checkpoint

**Mitigation strategies**:
1. **Pruning**: Keep only N most recent checkpoints
2. **Clean-only retention**: Only keep checkpoints from clean execution
3. **Compression**: Use gzip for checkpoint files
4. **Archiving**: Move old checkpoints to archive storage

## Error Handling

### Checkpoint Save Failures

**Scenarios**:
- Disk full
- Permission errors
- Serialization failures
- Concurrent writes

**Handling**:
```python
try:
    await checkpoint_store.save_checkpoint(session_id, checkpoint)
except CheckpointSaveError as e:
    # Log warning but don't fail execution
    logger.warning(f"Failed to save checkpoint: {e}")
    # Continue execution without checkpoint
```

### Checkpoint Load Failures

**Scenarios**:
- Checkpoint file corrupted
- Checkpoint format incompatible
- Referenced conversation state missing

**Handling**:
```python
try:
    checkpoint = await checkpoint_store.load_checkpoint(session_id, checkpoint_id)
except CheckpointLoadError as e:
    # Try to find previous valid checkpoint
    checkpoints = await checkpoint_store.list_checkpoints(session_id)
    for cp in reversed(checkpoints):
        try:
            checkpoint = await checkpoint_store.load_checkpoint(session_id, cp.checkpoint_id)
            logger.info(f"Fell back to checkpoint {cp.checkpoint_id}")
            break
        except CheckpointLoadError:
            continue
    else:
        raise ValueError(f"No valid checkpoints found for session {session_id}")
```

### Resume Failures

**Scenarios**:
- Checkpoint state inconsistent with current graph
- Node no longer exists in updated agent code
- Memory keys missing required values

**Handling**:
1. **Validation**: Verify checkpoint compatibility before resume
2. **Graceful degradation**: Resume from earlier checkpoint if possible
3. **User notification**: Clear error messages about why resume failed

## Migration Path

### Backward Compatibility

**Existing sessions** (without checkpoints):
- Can still be executed normally
- Checkpoint system is opt-in per agent
- No breaking changes to existing APIs

**Enabling checkpoints**:
```python
# Option 1: Agent-level default
class MyAgent(Agent):
    checkpoint_config = CheckpointConfig(
        checkpoint_on_node_complete=True,
    )

# Option 2: Runtime override
runtime = create_agent_runtime(
    agent=my_agent,
    checkpoint_config=CheckpointConfig(...),
)

# Option 3: Per-execution
result = await executor.execute(
    graph=graph,
    goal=goal,
    checkpoint_config=CheckpointConfig(...),
)
```

### Gradual Rollout

1. **Phase 1**: Core infrastructure, no user-facing features
2. **Phase 2**: Opt-in for specific agents via config
3. **Phase 3**: User-facing MCP tools and CLI
4. **Phase 4**: Enable by default for all new agents
5. **Phase 5**: TUI integration

## Future Enhancements

### 1. Incremental Checkpoints

Instead of full state snapshots, store only deltas:
```python
@dataclass
class IncrementalCheckpoint:
    """Checkpoint with only changed state."""
    base_checkpoint_id: str  # Parent checkpoint
    memory_delta: dict[str, Any]  # Only changed keys
    added_outputs: dict[str, Any]  # Only new outputs
```

### 2. Distributed Checkpointing

For long-running agents, checkpoint to cloud storage:
```python
checkpoint_config = CheckpointConfig(
    storage_backend="s3",  # or "gcs", "azure"
    storage_url="s3://my-bucket/checkpoints/",
)
```

### 3. Checkpoint Compression

Compress large memory states:
```python
checkpoint_config = CheckpointConfig(
    compress=True,
    compression_threshold_bytes=100_000,  # Compress if > 100KB
)
```

### 4. Smart Checkpoint Selection

Use heuristics to decide when to checkpoint:
```python
class SmartCheckpointStrategy:
    def should_checkpoint(self, context: ExecutionContext) -> bool:
        # Checkpoint after expensive nodes
        if context.node_latency_ms > 30_000:
            return True
        # Checkpoint before risky operations
        if context.node_id in ["api_call", "external_tool"]:
            return True
        # Checkpoint after significant memory changes
        if context.memory_delta_size > 10:
            return True
        return False
```

## Security Considerations

### 1. Sensitive Data in Checkpoints

**Problem**: Checkpoints may contain sensitive data (API keys, credentials, PII)

**Mitigation**:
```python
@dataclass
class CheckpointConfig:
    # Exclude sensitive keys from checkpoint
    exclude_memory_keys: list[str] = field(default_factory=lambda: [
        "api_key",
        "credentials",
        "access_token",
    ])

    # Encrypt checkpoint files
    encrypt_checkpoints: bool = True
    encryption_key_source: str = "keychain"  # or "env_var", "file"
```

### 2. Checkpoint Tampering

**Problem**: Malicious modification of checkpoint files

**Mitigation**:
```python
@dataclass
class Checkpoint:
    # Add cryptographic signature
    signature: str  # HMAC of checkpoint content

    def verify_signature(self, secret_key: str) -> bool:
        """Verify checkpoint hasn't been tampered with."""
        ...
```

## References

- [RUNTIME_LOGGING.md](./RUNTIME_LOGGING.md) - Current logging system
- [session_state.py](../schemas/session_state.py) - Session state schema
- [session_store.py](../storage/session_store.py) - Session storage
- [executor.py](../graph/executor.py) - Graph executor
- [event_loop_node.py](../graph/event_loop_node.py) - EventLoop implementation
