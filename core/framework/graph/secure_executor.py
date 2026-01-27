"""
Security-hardened GraphExecutor with enhanced validation and monitoring
"""
import asyncio
import logging
import sys
import time
from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Any

from framework.graph.edge import GraphSpec
from framework.graph.goal import Goal
from framework.graph.node import (
    FunctionNode,
    LLMNode,
    NodeContext,
    NodeProtocol,
    NodeResult,
    NodeSpec,
    RouterNode,
    SharedMemory,
)
from framework.graph.output_cleaner import CleansingConfig, OutputCleaner
from framework.graph.validator import OutputValidator
from framework.llm.provider import LLMProvider, Tool
from framework.runtime.core import Runtime
from framework.security import AuditLogger, SecurityEvent, InputSanitizer, SecurityViolation


@dataclass
class SecurityConfig:
    """Security configuration for GraphExecutor."""
    enable_sanitization: bool = True
    enable_audit_logging: bool = True
    max_execution_time: float = 300.0
    max_memory_mb: int = 512
    max_output_length: int = 10000
    validate_inputs: bool = True
    validate_outputs: bool = True


@dataclass
class ExecutionMetrics:
    """Enhanced execution metrics."""
    success: bool = False
    output: dict[str, Any] = field(default_factory=dict)
    error: str | None = None
    steps_executed: int = 0
    total_tokens: int = 0
    total_latency_ms: int = 0
    path: list[str] = field(default_factory=list)
    paused_at: str | None = None
    session_state: dict[str, Any] = field(default_factory=dict)
    
    # Security metrics
    security_violations: list[str] = field(default_factory=list)
    input_sanitizations: int = 0
    output_validations: int = 0
    memory_peak_mb: float = 0.0
    execution_time_seconds: float = 0.0


class SecureGraphExecutor:
    """
    Security-hardened graph executor with comprehensive validation.
    
    Enhancements:
    - Input/output sanitization
    - Resource usage monitoring
    - Security violation tracking
    - Enhanced error handling
    - Performance metrics
    - Audit logging
    """

    def __init__(
        self,
        runtime: Runtime,
        llm: LLMProvider | None = None,
        tools: list[Tool] | None = None,
        tool_executor: Callable | None = None,
        node_registry: dict[str, NodeProtocol] | None = None,
        approval_callback: Callable | None = None,
        cleansing_config: CleansingConfig | None = None,
        security_config: SecurityConfig | None = None,
        audit_logger: AuditLogger | None = None,
    ):
        """
        Initialize the secure executor.
        
        Args:
            runtime: Runtime for decision logging
            llm: LLM provider for LLM nodes
            tools: Available tools
            tool_executor: Function to execute tools
            node_registry: Custom node implementations by ID
            approval_callback: Optional callback for human-in-the-loop approval
            cleansing_config: Optional output cleansing configuration
            security_config: Security configuration
            audit_logger: Audit logger for security events
        """
        self.runtime = runtime
        self.llm = llm
        self.tools = tools or []
        self.tool_executor = tool_executor
        self.node_registry = node_registry or {}
        self.approval_callback = approval_callback
        self.validator = OutputValidator()
        self.logger = logging.getLogger(__name__)
        
        # Security components
        self._security_config = security_config or SecurityConfig()
        self._input_sanitizer = InputSanitizer() if self._security_config.enable_sanitization else None
        self._audit_logger = audit_logger
        
        # Initialize output cleaner
        self.cleansing_config = cleansing_config or CleansingConfig()
        self.output_cleaner = OutputCleaner(
            config=self.cleansing_config,
            llm_provider=llm,
        )
        
        # Performance tracking
        self._executions_completed = 0
        self._executions_failed = 0
        self._total_tokens_used = 0
        self._start_time = time.time()

    def _validate_tools(self, graph: GraphSpec) -> list[str]:
        """
        Validate that all tools declared by nodes are available.
        Enhanced with security checks.

        Returns:
            List of error messages (empty if all tools are available)
        """
        errors = []
        available_tool_names = {t.name for t in self.tools}

        for node in graph.nodes:
            if node.tools:
                missing = set(node.tools) - available_tool_names
                if missing:
                    avail = sorted(available_tool_names) if available_tool_names else "none"
                    errors.append(
                        f"Node '{node.name}' (id={node.id}) requires tools "
                        f"{sorted(missing)} but they are not registered. "
                        f"Available tools: {avail}"
                    )
                    
                # Security: Check for dangerous tools
                dangerous_tools = {'shell', 'exec', 'eval', 'system', 'subprocess'}
                for tool in node.tools:
                    if any(dangerous in tool.lower() for dangerous in dangerous_tools):
                        errors.append(
                            f"Node '{node.name}' (id={node.id}) uses potentially dangerous tool: {tool}"
                        )

        return errors

    def _monitor_memory_usage(self) -> float:
        """
        Monitor current memory usage in MB.
        
        Returns:
            Memory usage in MB
        """
        try:
            import psutil
            process = psutil.Process()
            return process.memory_info().rss / 1024 / 1024
        except ImportError:
            # Fallback to basic measurement
            return 0.0

    def _check_resource_limits(self, execution_id: str) -> None:
        """
        Check if execution exceeds resource limits.
        
        Args:
            execution_id: Execution identifier for logging
            
        Raises:
            RuntimeError: If resource limits exceeded
        """
        current_memory = self._monitor_memory_usage()
        
        if current_memory > self._security_config.max_memory_mb:
            error_msg = f"Memory limit exceeded: {current_memory:.2f}MB > {self._security_config.max_memory_mb}MB"
            
            if self._audit_logger:
                self._audit_logger.log_resource_exceeded(
                    resource_type="memory",
                    current_value=current_memory,
                    limit=self._security_config.max_memory_mb,
                    execution_id=execution_id
                )
            
            raise RuntimeError(error_msg)

    def _sanitize_input_data(self, input_data: dict[str, Any], execution_id: str) -> dict[str, Any]:
        """
        Sanitize input data before execution.
        
        Args:
            input_data: Raw input data
            execution_id: Execution identifier
            
        Returns:
            Sanitized input data
        """
        if not self._input_sanitizer:
            return input_data
            
        try:
            sanitized = self._input_sanitizer.sanitize_dict(input_data)
            
            if self._audit_logger and sanitized != input_data:
                self._audit_logger.log_security_violation(
                    violation_type="input_sanitization",
                    description=f"Input data sanitized during execution {execution_id}",
                    severity="low"
                )
                
            return sanitized
            
        except SecurityViolation as e:
            if self._audit_logger:
                self._audit_logger.log_security_violation(
                    violation_type=e.violation_type,
                    description=e.description,
                    field_path=e.field_path,
                    original_value=e.original_value,
                    severity=e.severity
                )
            
            if e.severity == "critical":
                raise RuntimeError(f"Critical security violation: {e.description}")
                
            # Continue with sanitized data for non-critical violations
            return {}

    async def execute(
        self,
        graph: GraphSpec,
        goal: Goal,
        input_data: dict[str, Any] | None = None,
        session_state: dict[str, Any] | None = None,
    ) -> ExecutionMetrics:
        """
        Execute a graph for a goal with enhanced security and monitoring.
        
        Args:
            graph: The graph specification
            goal: The goal driving execution
            input_data: Initial input data
            session_state: Optional session state to resume from
            
        Returns:
            ExecutionMetrics with comprehensive execution data
        """
        execution_id = f"exec_{int(time.time() * 1000)}"
        start_time = time.time()
        
        try:
            # Validate graph
            errors = graph.validate()
            if errors:
                return ExecutionMetrics(
                    success=False,
                    error=f"Invalid graph: {errors}",
                    execution_time_seconds=time.time() - start_time
                )

            # Validate tool availability
            tool_errors = self._validate_tools(graph)
            if tool_errors:
                self.logger.error("❌ Tool validation failed:")
                for err in tool_errors:
                    self.logger.error(f"   • {err}")
                return ExecutionMetrics(
                    success=False,
                    error=(
                        f"Missing tools: {'; '.join(tool_errors)}. "
                        "Register tools via ToolRegistry or remove tool declarations."
                    ),
                    execution_time_seconds=time.time() - start_time
                )

            # Sanitize input data
            sanitized_input = self._sanitize_input_data(input_data or {}, execution_id)
            
            # Initialize execution state
            memory = SharedMemory()
            input_sanitizations = 0
            output_validations = 0
            security_violations = []
            memory_peak = 0.0

            # Restore session state if provided
            if session_state and "memory" in session_state:
                memory_data = session_state["memory"]
                if isinstance(memory_data, dict):
                    for key, value in memory_data.items():
                        memory.write(key, value)
                    self.logger.info(f"📥 Restored session state with {len(memory_data)} memory keys")
                else:
                    self.logger.warning(
                        f"⚠️ Invalid memory data type in session state: "
                        f"{type(memory_data).__name__}, expected dict"
                    )

            # Write sanitized input data to memory
            for key, value in sanitized_input.items():
                memory.write(key, value)
                if value != (input_data or {}).get(key):
                    input_sanitizations += 1

            path: list[str] = []
            total_tokens = 0
            total_latency = 0
            node_retry_counts: dict[str, int] = {}

            # Determine entry point
            current_node_id = graph.get_entry_point(session_state)
            steps = 0

            if session_state and current_node_id != graph.entry_node:
                self.logger.info(f"🔄 Resuming from: {current_node_id}")

            # Start run
            _run_id = self.runtime.start_run(
                goal_id=goal.id,
                goal_description=goal.description,
                input_data=sanitized_input,
            )

            self.logger.info(f"🚀 Starting secure execution: {goal.name}")
            self.logger.info(f"   Goal: {goal.description}")
            self.logger.info(f"   Entry node: {graph.entry_node}")
            self.logger.info(f"   Execution ID: {execution_id}")

            try:
                while steps < graph.max_steps:
                    steps += 1
                    
                    # Check resource limits
                    self._check_resource_limits(execution_id)
                    current_memory = self._monitor_memory_usage()
                    memory_peak = max(memory_peak, current_memory)

                    # Get current node
                    node_spec = graph.get_node(current_node_id)
                    if node_spec is None:
                        raise RuntimeError(f"Node not found: {current_node_id}")

                    path.append(current_node_id)

                    # Check for pause (HITL) before execution
                    if current_node_id in graph.pause_nodes:
                        self.logger.info(f"⏸ Paused at HITL node: {node_spec.name}")

                    self.logger.info(f"\n▶ Step {steps}: {node_spec.name} ({node_spec.node_type})")
                    self.logger.info(f"   Inputs: {node_spec.input_keys}")
                    self.logger.info(f"   Outputs: {node_spec.output_keys}")

                    # Build context for node
                    ctx = self._build_context(
                        node_spec=node_spec,
                        memory=memory,
                        goal=goal,
                        input_data=sanitized_input,
                    )

                    # Log actual input data
                    if node_spec.input_keys:
                        self.logger.info("   Reading from memory:")
                        for key in node_spec.input_keys:
                            value = memory.read(key)
                            if value is not None:
                                value_str = str(value)
                                if len(value_str) > 200:
                                    value_str = value_str[:200] + "..."
                                self.logger.info(f"      {key}: {value_str}")

                    # Get or create node implementation
                    node_impl = self._get_node_implementation(node_spec)

                    # Enhanced input validation
                    if self._security_config.validate_inputs:
                        validation_errors = node_impl.validate_input(ctx)
                        if validation_errors:
                            self.logger.warning(f"⚠ Input validation warnings: {validation_errors}")
                            self.runtime.report_problem(
                                severity="warning",
                                description=f"Validation errors for {current_node_id}: {validation_errors}",
                            )

                    # Execute node with timeout
                    execution_start = time.time()
                    self.logger.info("   Executing...")
                    
                    try:
                        # Enforce execution timeout
                        result = await asyncio.wait_for(
                            node_impl.execute(ctx),
                            timeout=self._security_config.max_execution_time
                        )
                    except asyncio.TimeoutError:
                        error_msg = f"Node execution exceeded timeout of {self._security_config.max_execution_time}s"
                        self.logger.error(f"   ✗ {error_msg}")
                        
                        if self._audit_logger:
                            self._audit_logger.log_security_violation(
                                violation_type="timeout_exceeded",
                                description=error_msg,
                                field_path=f"node.{current_node_id}",
                                severity="high"
                            )
                            
                        raise RuntimeError(error_msg)

                    execution_time = (time.time() - execution_start) * 1000

                    # Enhanced output validation
                    if result.success and self._security_config.validate_outputs:
                        if result.output and node_spec.output_keys:
                            validation = self.validator.validate_all(
                                output=result.output,
                                expected_keys=node_spec.output_keys,
                                check_hallucination=True,
                            )
                            output_validations += 1
                            
                            if not validation.success:
                                self.logger.error(f"   ✗ Output validation failed: {validation.error}")
                                
                                if self._audit_logger:
                                    self._audit_logger.log_security_violation(
                                        violation_type="output_validation_failed",
                                        description=validation.error,
                                        field_path=f"node.{current_node_id}.output",
                                        severity="medium"
                                    )
                                    
                                result = NodeResult(
                                    success=False,
                                    error=f"Output validation failed: {validation.error}",
                                    output={},
                                    tokens_used=result.tokens_used,
                                    latency_ms=result.latency_ms,
                                )

                    if result.success:
                        self.logger.info(
                            f"   ✓ Success (tokens: {result.tokens_used}, "
                            f"latency: {result.latency_ms}ms)"
                        )

                        # Generate and log human-readable summary
                        summary = result.to_summary(node_spec)
                        self.logger.info(f"   📝 Summary: {summary}")

                        # Log what was written to memory
                        if result.output:
                            self.logger.info("   Written to memory:")
                            for key, value in result.output.items():
                                value_str = str(value)
                                if len(value_str) > 200:
                                    value_str = value_str[:200] + "..."
                                self.logger.info(f"      {key}: {value_str}")
                    else:
                        self.logger.error(f"   ✗ Failed: {result.error}")

                    total_tokens += result.tokens_used
                    total_latency += execution_time

                    # Handle failure with retry logic
                    if not result.success:
                        node_retry_counts[current_node_id] = (
                            node_retry_counts.get(current_node_id, 0) + 1
                        )

                        if node_retry_counts[current_node_id] < node_spec.max_retries:
                            steps -= 1
                            retry_count = node_retry_counts[current_node_id]
                            self.logger.info(
                                f"   ↻ Retrying ({retry_count}/{node_spec.max_retries})..."
                            )
                            continue
                        else:
                            self.logger.error(
                                f"   ✗ Max retries ({node_spec.max_retries}) exceeded "
                                f"for node {current_node_id}"
                            )
                            self.runtime.report_problem(
                                severity="critical",
                                description=(
                                    f"Node {current_node_id} failed after "
                                    f"{node_spec.max_retries} attempts: {result.error}"
                                ),
                            )
                            self.runtime.end_run(
                                success=False,
                                output_data=memory.read_all(),
                                narrative=(
                                    f"Failed at {node_spec.name} after "
                                    f"{node_spec.max_retries} retries: {result.error}"
                                ),
                            )
                            
                            return ExecutionMetrics(
                                success=False,
                                error=(
                                    f"Node '{node_spec.name}' failed after "
                                    f"{node_spec.max_retries} attempts: {result.error}"
                                ),
                                output=memory.read_all(),
                                steps_executed=steps,
                                total_tokens=total_tokens,
                                total_latency_ms=int(total_latency),
                                path=path,
                                security_violations=security_violations,
                                input_sanitizations=input_sanitizations,
                                output_validations=output_validations,
                                memory_peak_mb=memory_peak,
                                execution_time_seconds=time.time() - start_time
                            )

                    # Check for pause node
                    if node_spec.id in graph.pause_nodes:
                        self.logger.info("💾 Saving session state after pause node")
                        saved_memory = memory.read_all()
                        session_state_out = {
                            "paused_at": node_spec.id,
                            "resume_from": f"{node_spec.id}_resume",
                            "memory": saved_memory,
                            "next_node": None,
                        }

                        self.runtime.end_run(
                            success=True,
                            output_data=saved_memory,
                            narrative=f"Paused at {node_spec.name} after {steps} steps",
                        )

                        return ExecutionMetrics(
                            success=True,
                            output=saved_memory,
                            steps_executed=steps,
                            total_tokens=total_tokens,
                            total_latency_ms=int(total_latency),
                            path=path,
                            paused_at=node_spec.id,
                            session_state=session_state_out,
                            security_violations=security_violations,
                            input_sanitizations=input_sanitizations,
                            output_validations=output_validations,
                            memory_peak_mb=memory_peak,
                            execution_time_seconds=time.time() - start_time
                        )

                    # Check for terminal node
                    if node_spec.id in graph.terminal_nodes:
                        self.logger.info(f"✓ Reached terminal node: {node_spec.name}")
                        break

                    # Determine next node
                    if result.next_node:
                        self.logger.info(f"   → Router directing to: {result.next_node}")
                        current_node_id = result.next_node
                    else:
                        next_node = self._follow_edges(
                            graph=graph,
                            goal=goal,
                            current_node_id=current_node_id,
                            current_node_spec=node_spec,
                            result=result,
                            memory=memory,
                        )
                        if next_node is None:
                            self.logger.info("   → No more edges, ending execution")
                            break
                        next_spec = graph.get_node(next_node)
                        self.logger.info(f"   → Next: {next_spec.name if next_spec else next_node}")
                        current_node_id = next_node

                    # Update input data for next node
                    sanitized_input = result.output

                # Successful completion
                output = memory.read_all()
                
                self.logger.info("\n✓ Execution complete!")
                self.logger.info(f"   Steps: {steps}")
                self.logger.info(f"   Path: {' → '.join(path)}")
                self.logger.info(f"   Total tokens: {total_tokens}")
                self.logger.info(f"   Total latency: {total_latency}ms")

                self.runtime.end_run(
                    success=True,
                    output_data=output,
                    narrative=f"Executed {steps} steps through path: {' -> '.join(path)}",
                )

                self._executions_completed += 1
                self._total_tokens_used += total_tokens

                if self._audit_logger:
                    self._audit_logger.log_execution_complete(
                        entry_point_id="graph_executor",
                        execution_id=execution_id,
                        success=True,
                        duration_ms=int(total_latency)
                    )

                return ExecutionMetrics(
                    success=True,
                    output=output,
                    steps_executed=steps,
                    total_tokens=total_tokens,
                    total_latency_ms=int(total_latency),
                    path=path,
                    security_violations=security_violations,
                    input_sanitizations=input_sanitizations,
                    output_validations=output_validations,
                    memory_peak_mb=memory_peak,
                    execution_time_seconds=time.time() - start_time
                )

            except Exception as e:
                self._executions_failed += 1
                
                if self._audit_logger:
                    self._audit_logger.log_security_violation(
                        violation_type="execution_error",
                        description=str(e),
                        field_path=f"execution.{execution_id}",
                        severity="high"
                    )
                    
                self.runtime.report_problem(
                    severity="critical",
                    description=str(e),
                )
                self.runtime.end_run(
                    success=False,
                    narrative=f"Failed at step {steps}: {e}",
                )
                return ExecutionMetrics(
                    success=False,
                    error=str(e),
                    steps_executed=steps,
                    path=path,
                    security_violations=security_violations,
                    input_sanitizations=input_sanitizations,
                    output_validations=output_validations,
                    memory_peak_mb=memory_peak,
                    execution_time_seconds=time.time() - start_time
                )

        except Exception as e:
            self.logger.error(f"Critical error in execution: {e}")
            return ExecutionMetrics(
                success=False,
                error=f"Critical execution error: {e}",
                execution_time_seconds=time.time() - start_time
            )

    def _build_context(
        self,
        node_spec: NodeSpec,
        memory: SharedMemory,
        goal: Goal,
        input_data: dict[str, Any],
    ) -> NodeContext:
        """Build execution context for a node."""
        # Filter tools to those available to this node
        available_tools = []
        if node_spec.tools:
            available_tools = [t for t in self.tools if t.name in node_spec.tools]

        # Create scoped memory view
        scoped_memory = memory.with_permissions(
            read_keys=node_spec.input_keys,
            write_keys=node_spec.output_keys,
        )

        return NodeContext(
            runtime=self.runtime,
            node_id=node_spec.id,
            node_spec=node_spec,
            memory=scoped_memory,
            input_data=input_data,
            llm=self.llm,
            available_tools=available_tools,
            goal_context=goal.to_prompt_context(),
            goal=goal,
        )

    # Node type validation (same as original)
    VALID_NODE_TYPES = {"llm_tool_use", "llm_generate", "router", "function", "human_input"}

    def _get_node_implementation(self, node_spec: NodeSpec) -> NodeProtocol:
        """Get or create a node implementation."""
        # Check registry first
        if node_spec.id in self.node_registry:
            return self.node_registry[node_spec.id]

        # Validate node type
        if node_spec.node_type not in self.VALID_NODE_TYPES:
            raise RuntimeError(
                f"Invalid node type '{node_spec.node_type}' for node '{node_spec.id}'. "
                f"Must be one of: {sorted(self.VALID_NODE_TYPES)}. "
                f"Use 'llm_tool_use' for nodes that call tools, 'llm_generate' for text generation."
            )

        # Create based on type
        if node_spec.node_type == "llm_tool_use":
            if not node_spec.tools:
                raise RuntimeError(
                    f"Node '{node_spec.id}' is type 'llm_tool_use' but declares no tools. "
                    "Either add tools to the node or change type to 'llm_generate'."
                )
            return LLMNode(tool_executor=self.tool_executor, require_tools=True)

        if node_spec.node_type == "llm_generate":
            return LLMNode(tool_executor=None, require_tools=False)

        if node_spec.node_type == "router":
            return RouterNode()

        if node_spec.node_type == "function":
            raise RuntimeError(
                f"Function node '{node_spec.id}' not registered. Register with node_registry."
            )

        if node_spec.node_type == "human_input":
            return LLMNode(tool_executor=None, require_tools=False)

        raise RuntimeError(f"Unhandled node type: {node_spec.node_type}")

    def _follow_edges(
        self,
        graph: GraphSpec,
        goal: Goal,
        current_node_id: str,
        current_node_spec: Any,
        result: NodeResult,
        memory: SharedMemory,
    ) -> str | None:
        """Determine the next node by following edges."""
        edges = graph.get_outgoing_edges(current_node_id)

        for edge in edges:
            target_node_spec = graph.get_node(edge.target)

            if edge.should_traverse(
                source_success=result.success,
                source_output=result.output,
                memory=memory.read_all(),
                llm=self.llm,
                goal=goal,
                source_node_name=current_node_spec.name if current_node_spec else current_node_id,
                target_node_name=target_node_spec.name if target_node_spec else edge.target,
            ):
                # Validate and clean output before mapping inputs
                if self.cleansing_config.enabled and target_node_spec:
                    output_to_validate = result.output

                    validation = self.output_cleaner.validate_output(
                        output=output_to_validate,
                        source_node_id=current_node_id,
                        target_node_spec=target_node_spec,
                    )

                    if not validation.valid:
                        self.logger.warning(f"⚠ Output validation failed: {validation.errors}")

                        # Clean the output
                        cleaned_output = self.output_cleaner.clean_output(
                            output=output_to_validate,
                            source_node_id=current_node_id,
                            target_node_spec=target_node_spec,
                            validation_errors=validation.errors,
                        )

                        # Update result with cleaned output
                        result.output = cleaned_output

                        # Write cleaned output back to memory
                        for key, value in cleaned_output.items():
                            memory.write(key, value)

                        # Revalidate
                        revalidation = self.output_cleaner.validate_output(
                            output=cleaned_output,
                            source_node_id=current_node_id,
                            target_node_spec=target_node_spec,
                        )

                        if revalidation.valid:
                            self.logger.info("✓ Output cleaned and validated successfully")
                        else:
                            self.logger.error(
                                f"✗ Cleaning failed, errors remain: {revalidation.errors}"
                            )

                # Map inputs
                mapped = edge.map_inputs(result.output, memory.read_all())
                for key, value in mapped.items():
                    memory.write(key, value)

                return edge.target

        return None

    def register_node(self, node_id: str, implementation: NodeProtocol) -> None:
        """Register a custom node implementation."""
        self.node_registry[node_id] = implementation

    def register_function(self, node_id: str, func: Callable) -> None:
        """Register a function as a node."""
        self.node_registry[node_id] = FunctionNode(func)

    def get_stats(self) -> dict:
        """Get comprehensive executor statistics."""
        uptime = time.time() - self._start_time
        
        return {
            "executions_completed": self._executions_completed,
            "executions_failed": self._executions_failed,
            "total_tokens_used": self._total_tokens_used,
            "uptime_seconds": uptime,
            "success_rate": (
                self._executions_completed / 
                max(1, self._executions_completed + self._executions_failed)
            ),
            "tokens_per_second": self._total_tokens_used / uptime if uptime > 0 else 0,
            "security": {
                "sanitization_enabled": bool(self._input_sanitizer),
                "input_validation_enabled": self._security_config.validate_inputs,
                "output_validation_enabled": self._security_config.validate_outputs,
                "max_execution_time": self._security_config.max_execution_time,
                "max_memory_mb": self._security_config.max_memory_mb,
            },
            "tools_count": len(self.tools),
            "nodes_registered": len(self.node_registry)
        }