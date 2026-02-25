"""
GraphBuilder Workflow - Enforced incremental building with HITL approval.

The build process:
1. Define Goal → APPROVE
2. Add Node → VALIDATE → TEST → APPROVE
3. Add Edge → VALIDATE → TEST → APPROVE
4. Repeat until graph is complete
5. Final integration test → APPROVE
6. Export

Each step requires validation and human approval before proceeding.
You cannot skip steps or bypass validation.
"""

from collections.abc import Callable
from datetime import datetime
from enum import StrEnum
from pathlib import Path
from typing import Any

from pydantic import BaseModel, Field

from framework.graph.edge import EdgeCondition, EdgeSpec, GraphSpec
from framework.graph.goal import Goal
from framework.graph.node import NodeSpec


class BuildPhase(StrEnum):
    """Current phase of the build process."""

    INIT = "init"  # Just started
    GOAL_DRAFT = "goal_draft"  # Drafting goal
    GOAL_APPROVED = "goal_approved"  # Goal approved
    ADDING_NODES = "adding_nodes"  # Adding nodes
    ADDING_EDGES = "adding_edges"  # Adding edges
    TESTING = "testing"  # Running tests
    APPROVED = "approved"  # Fully approved
    EXPORTED = "exported"  # Exported to file


class ValidationResult(BaseModel):
    """Result of a validation check."""

    valid: bool
    errors: list[str] = Field(default_factory=list)
    warnings: list[str] = Field(default_factory=list)
    suggestions: list[str] = Field(default_factory=list)


class TestCase(BaseModel):
    """A test case for validating agent behavior."""

    id: str
    description: str
    input: dict[str, Any]
    expected_output: Any = None  # None means just check it doesn't error
    expected_contains: str | None = None


class TestResult(BaseModel):
    """Result of running a test case."""

    test_id: str
    passed: bool
    actual_output: Any = None
    error: str | None = None
    execution_path: list[str] = Field(default_factory=list)


class BuildSession(BaseModel):
    """
    Persistent build session state.

    Saved after each approved step so you can resume later.
    """

    id: str
    name: str
    phase: BuildPhase = BuildPhase.INIT
    created_at: datetime = Field(default_factory=datetime.now)
    updated_at: datetime = Field(default_factory=datetime.now)

    # The artifacts being built
    goal: Goal | None = None
    nodes: list[NodeSpec] = Field(default_factory=list)
    edges: list[EdgeSpec] = Field(default_factory=list)

    # Test cases
    test_cases: list[TestCase] = Field(default_factory=list)
    test_results: list[TestResult] = Field(default_factory=list)

    # Approval history
    approvals: list[dict[str, Any]] = Field(default_factory=list)

    # Tools (stored as dicts for serialization)
    tools: list[dict[str, Any]] = Field(default_factory=list)

    model_config = {"extra": "allow"}


class GraphBuilder:
    """
    Enforced incremental graph building with HITL approval.

    Usage:
        builder = GraphBuilder("my-agent")

        # Step 1: Define and approve goal
        builder.set_goal(goal)
        builder.validate()  # Must pass
        builder.approve("Goal looks good")  # Human approval required

        # Step 2: Add nodes one by one
        builder.add_node(node_spec)
        builder.validate()  # Must pass
        builder.test(test_case)  # Must pass
        builder.approve("Node works")

        # Step 3: Add edges
        builder.add_edge(edge_spec)
        builder.validate()
        builder.approve("Edge correct")

        # Step 4: Final approval
        builder.run_all_tests()
        builder.final_approve("Ready for production")

        # Step 5: Export
        graph = builder.export()
    """

    def __init__(
        self,
        name: str,
        storage_path: Path | str | None = None,
        session_id: str | None = None,
    ):
        self.storage_path = Path(storage_path) if storage_path else Path.home() / ".core" / "builds"
        self.storage_path.mkdir(parents=True, exist_ok=True)

        if session_id:
            self.session = self._load_session(session_id)
        else:
            self.session = BuildSession(
                id=f"build_{datetime.now().strftime('%Y%m%d_%H%M%S')}",
                name=name,
            )

        self._pending_validation: ValidationResult | None = None

    # =========================================================================
    # PHASE 1: GOAL
    # =========================================================================

    def set_goal(self, goal: Goal) -> ValidationResult:
        """
        Set the goal for this agent.

        Returns validation result. Must call approve() after validation passes.
        """
        self._require_phase([BuildPhase.INIT, BuildPhase.GOAL_DRAFT])

        self.session.goal = goal
        self.session.phase = BuildPhase.GOAL_DRAFT

        validation = self._validate_goal(goal)
        self._pending_validation = validation
        self._save_session()

        return validation

    def _validate_goal(self, goal: Goal) -> ValidationResult:
        """Validate a goal definition."""
        errors = []
        warnings = []
        suggestions = []

        if not goal.id:
            errors.append("Goal must have an id")
        if not goal.name:
            errors.append("Goal must have a name")
        if not goal.description:
            errors.append("Goal must have a description")

        if not goal.success_criteria:
            errors.append("Goal must have at least one success criterion")
        else:
            for sc in goal.success_criteria:
                if not sc.description:
                    errors.append(f"Success criterion '{sc.id}' needs a description")

        if not goal.constraints:
            warnings.append("Consider adding constraints to define boundaries")

        if not goal.required_capabilities:
            suggestions.append("Specify required_capabilities (e.g., ['llm', 'tools'])")

        return ValidationResult(
            valid=len(errors) == 0,
            errors=errors,
            warnings=warnings,
            suggestions=suggestions,
        )

    # =========================================================================
    # PHASE 2: NODES
    # =========================================================================

    def add_node(self, node: NodeSpec) -> ValidationResult:
        """
        Add a node to the graph.

        Returns validation result. Must call approve() after validation passes.
        """
        self._require_phase([BuildPhase.GOAL_APPROVED, BuildPhase.ADDING_NODES])

        # Check for duplicate
        if any(n.id == node.id for n in self.session.nodes):
            return ValidationResult(
                valid=False,
                errors=[f"Node with id '{node.id}' already exists"],
            )

        self.session.nodes.append(node)
        self.session.phase = BuildPhase.ADDING_NODES

        validation = self._validate_node(node)
        self._pending_validation = validation
        self._save_session()

        return validation

    def _validate_node(self, node: NodeSpec) -> ValidationResult:
        """Validate a node definition."""
        errors = []
        warnings = []
        suggestions = []

        if not node.id:
            errors.append("Node must have an id")
        if not node.name:
            errors.append("Node must have a name")
        if not node.description:
            warnings.append(f"Node '{node.id}' should have a description")

        # Type-specific validation
        if node.node_type == "event_loop":
            if node.tools and not node.system_prompt:
                warnings.append(f"Event loop node '{node.id}' should have a system_prompt")

        if node.node_type == "router":
            if not node.routes:
                errors.append(f"Router node '{node.id}' must specify routes")

        # Check input/output keys
        if not node.input_keys:
            suggestions.append(f"Consider specifying input_keys for '{node.id}'")
        if not node.output_keys:
            suggestions.append(f"Consider specifying output_keys for '{node.id}'")

        return ValidationResult(
            valid=len(errors) == 0,
            errors=errors,
            warnings=warnings,
            suggestions=suggestions,
        )

    def update_node(self, node_id: str, **updates) -> ValidationResult:
        """Update an existing node."""
        self._require_phase([BuildPhase.ADDING_NODES])

        for i, node in enumerate(self.session.nodes):
            if node.id == node_id:
                node_dict = node.model_dump()
                node_dict.update(updates)
                updated_node = NodeSpec(**node_dict)
                self.session.nodes[i] = updated_node

                validation = self._validate_node(updated_node)
                self._pending_validation = validation
                self._save_session()
                return validation

        return ValidationResult(valid=False, errors=[f"Node '{node_id}' not found"])

    def remove_node(self, node_id: str) -> ValidationResult:
        """Remove a node (only if no edges reference it)."""
        self._require_phase([BuildPhase.ADDING_NODES])

        # Check for edge references
        for edge in self.session.edges:
            if edge.source == node_id or edge.target == node_id:
                return ValidationResult(
                    valid=False,
                    errors=[f"Cannot remove node '{node_id}': referenced by edge '{edge.id}'"],
                )

        self.session.nodes = [n for n in self.session.nodes if n.id != node_id]
        self._save_session()

        return ValidationResult(valid=True)

    # =========================================================================
    # PHASE 3: EDGES
    # =========================================================================

    def add_edge(self, edge: EdgeSpec) -> ValidationResult:
        """
        Add an edge to the graph.

        Returns validation result. Must call approve() after validation passes.
        """
        self._require_phase([BuildPhase.ADDING_NODES, BuildPhase.ADDING_EDGES])

        # Check for duplicate
        if any(e.id == edge.id for e in self.session.edges):
            return ValidationResult(
                valid=False,
                errors=[f"Edge with id '{edge.id}' already exists"],
            )

        self.session.edges.append(edge)
        self.session.phase = BuildPhase.ADDING_EDGES

        validation = self._validate_edge(edge)
        self._pending_validation = validation
        self._save_session()

        return validation

    def _validate_edge(self, edge: EdgeSpec) -> ValidationResult:
        """Validate an edge definition."""
        errors = []
        warnings = []

        if not edge.id:
            errors.append("Edge must have an id")

        # Check source exists
        if not any(n.id == edge.source for n in self.session.nodes):
            errors.append(f"Edge source '{edge.source}' not found in nodes")

        # Check target exists
        if not any(n.id == edge.target for n in self.session.nodes):
            errors.append(f"Edge target '{edge.target}' not found in nodes")

        # Warn about conditional edges without expressions
        if edge.condition == EdgeCondition.CONDITIONAL and not edge.condition_expr:
            warnings.append(f"Conditional edge '{edge.id}' has no condition_expr")

        return ValidationResult(
            valid=len(errors) == 0,
            errors=errors,
            warnings=warnings,
        )

    # =========================================================================
    # VALIDATION & TESTING
    # =========================================================================

    def validate(self) -> ValidationResult:
        """Validate the entire current graph state."""
        errors = []
        warnings = []

        # Must have a goal
        if not self.session.goal:
            errors.append("No goal defined")
            return ValidationResult(valid=False, errors=errors)

        # Must have at least one node
        if not self.session.nodes:
            errors.append("No nodes defined")

        # Check for entry node
        entry_candidates = []
        for node in self.session.nodes:
            # A node is an entry candidate if no edges point to it
            if not any(e.target == node.id for e in self.session.edges):
                entry_candidates.append(node.id)

        if len(entry_candidates) == 0 and self.session.nodes:
            errors.append("No entry node found (all nodes have incoming edges)")
        elif len(entry_candidates) > 1:
            warnings.append(f"Multiple entry candidates: {entry_candidates}. Specify one.")

        # Check for terminal nodes
        terminal_candidates = []
        for node in self.session.nodes:
            if not any(e.source == node.id for e in self.session.edges):
                terminal_candidates.append(node.id)

        if not terminal_candidates and self.session.nodes:
            warnings.append("No terminal nodes found (all nodes have outgoing edges)")

        # Check reachability from ALL entry candidates (not just the first one).
        # Agents with async entry points have multiple nodes with no incoming
        # edges (e.g., a primary entry node and an event-driven entry node).
        if entry_candidates and self.session.nodes:
            reachable = set()
            for candidate in entry_candidates:
                reachable |= self._compute_reachable(candidate)
            unreachable = [n.id for n in self.session.nodes if n.id not in reachable]
            if unreachable:
                errors.append(f"Unreachable nodes: {unreachable}")

        validation = ValidationResult(
            valid=len(errors) == 0,
            errors=errors,
            warnings=warnings,
        )
        self._pending_validation = validation
        return validation

    def _compute_reachable(self, start: str) -> set[str]:
        """Compute all nodes reachable from start."""
        reachable = set()
        to_visit = [start]

        while to_visit:
            current = to_visit.pop()
            if current in reachable:
                continue
            reachable.add(current)

            for edge in self.session.edges:
                if edge.source == current:
                    to_visit.append(edge.target)

            # Also follow router routes
            for node in self.session.nodes:
                if node.id == current and node.routes:
                    for target in node.routes.values():
                        to_visit.append(target)

        return reachable

    def add_test(self, test: TestCase) -> None:
        """Add a test case."""
        self.session.test_cases.append(test)
        self._save_session()

    async def run_test_async(
        self,
        test: TestCase,
        executor_factory: Callable,
    ) -> TestResult:
        """
        Run a single test case asynchronously.

        This method is safe to call from async contexts (Jupyter, FastAPI, etc.).
        executor_factory should return a configured GraphExecutor.
        """
        self._require_phase([BuildPhase.ADDING_NODES, BuildPhase.ADDING_EDGES, BuildPhase.TESTING])
        self.session.phase = BuildPhase.TESTING

        try:
            # Build temporary graph for testing
            graph = self._build_graph()
            executor = executor_factory()

            # Run the test
            result = await executor.execute(
                graph=graph,
                goal=self.session.goal,
                input_data=test.input,
            )

            # Check result
            passed = result.success
            if test.expected_output is not None:
                passed = passed and (result.output.get("result") == test.expected_output)
            if test.expected_contains:
                output_str = str(result.output)
                passed = passed and (test.expected_contains in output_str)

            test_result = TestResult(
                test_id=test.id,
                passed=passed,
                actual_output=result.output,
                execution_path=result.path,
            )

        except Exception as e:
            test_result = TestResult(
                test_id=test.id,
                passed=False,
                error=str(e),
            )

        self.session.test_results.append(test_result)
        self._save_session()

        return test_result

    def run_test(
        self,
        test: TestCase,
        executor_factory: Callable,
    ) -> TestResult:
        """
        Run a single test case.

        This is a synchronous wrapper around run_test_async().
        If called from an async context (Jupyter, FastAPI, etc.), use run_test_async() instead.

        executor_factory should return a configured GraphExecutor.
        """
        import asyncio

        # Check if an event loop is already running
        # get_running_loop() returns a loop if one exists, or raises RuntimeError if none exists
        try:
            asyncio.get_running_loop()
        except RuntimeError:
            # No event loop running - safe to use asyncio.run()
            return asyncio.run(self.run_test_async(test, executor_factory))

        # Event loop is running - cannot use asyncio.run()
        raise RuntimeError(
            "Cannot call run_test() from an async context. "
            "An event loop is already running. "
            "Please use 'await builder.run_test_async(test, executor_factory)' instead."
        )

    def run_all_tests(self, executor_factory: Callable) -> list[TestResult]:
        """Run all test cases."""
        results = []
        for test in self.session.test_cases:
            result = self.run_test(test, executor_factory)
            results.append(result)
        return results

    # =========================================================================
    # APPROVAL
    # =========================================================================

    def approve(self, comment: str) -> bool:
        """
        Approve the current pending change.

        Must have a passing validation to approve.
        Returns True if approved, False if validation failed.
        """
        if self._pending_validation is None:
            raise RuntimeError("Nothing to approve. Run validation first.")

        if not self._pending_validation.valid:
            return False

        self.session.approvals.append(
            {
                "phase": self.session.phase.value,
                "comment": comment,
                "timestamp": datetime.now().isoformat(),
                "validation": self._pending_validation.model_dump(),
            }
        )

        # Advance phase if appropriate
        if self.session.phase == BuildPhase.GOAL_DRAFT:
            self.session.phase = BuildPhase.GOAL_APPROVED

        self._pending_validation = None
        self._save_session()

        return True

    def final_approve(self, comment: str) -> bool:
        """
        Final approval for the complete graph.

        Requires all tests to pass.
        """
        # Run final validation
        validation = self.validate()
        if not validation.valid:
            self._pending_validation = validation
            return False

        # Check test results
        if self.session.test_cases:
            failed_tests = [t for t in self.session.test_results if not t.passed]
            if failed_tests:
                self._pending_validation = ValidationResult(
                    valid=False,
                    errors=[f"Failed tests: {[t.test_id for t in failed_tests]}"],
                )
                return False

        self.session.phase = BuildPhase.APPROVED
        self.session.approvals.append(
            {
                "phase": "final",
                "comment": comment,
                "timestamp": datetime.now().isoformat(),
            }
        )

        self._save_session()
        return True

    # =========================================================================
    # EXPORT
    # =========================================================================

    def export(self) -> GraphSpec:
        """
        Export the approved graph.

        Requires final approval.
        """
        self._require_phase([BuildPhase.APPROVED])

        graph = self._build_graph()

        self.session.phase = BuildPhase.EXPORTED
        self._save_session()

        return graph

    def _build_graph(self) -> GraphSpec:
        """Build a GraphSpec from current session."""
        # Determine entry node
        entry_node = None
        for node in self.session.nodes:
            if not any(e.target == node.id for e in self.session.edges):
                entry_node = node.id
                break

        # Determine terminal nodes
        terminal_nodes = []
        for node in self.session.nodes:
            if not any(e.source == node.id for e in self.session.edges):
                terminal_nodes.append(node.id)

        # Collect all memory keys
        memory_keys = set()
        for node in self.session.nodes:
            memory_keys.update(node.input_keys)
            memory_keys.update(node.output_keys)

        return GraphSpec(
            id=f"{self.session.name}-graph",
            goal_id=self.session.goal.id if self.session.goal else "",
            entry_node=entry_node or "",
            terminal_nodes=terminal_nodes,
            nodes=self.session.nodes,
            edges=self.session.edges,
            memory_keys=list(memory_keys),
        )

    def export_to_file(self, path: Path | str) -> None:
        """Export the graph to a Python file."""
        self._require_phase([BuildPhase.APPROVED, BuildPhase.EXPORTED])

        graph = self._build_graph()

        # Generate Python code
        code = self._generate_code(graph)

        Path(path).write_text(code)
        self.session.phase = BuildPhase.EXPORTED
        self._save_session()

    def _generate_code(self, graph: GraphSpec) -> str:
        """Generate Python code for the graph."""
        lines = [
            '"""',
            f"Generated agent: {self.session.name}",
            f"Generated at: {datetime.now().isoformat()}",
            '"""',
            "",
            "from framework.graph import (",
            "    Goal, SuccessCriterion, Constraint,",
            "    NodeSpec, EdgeSpec, EdgeCondition,",
            ")",
            "from framework.graph.edge import GraphSpec",
            "from framework.graph.goal import GoalStatus",
            "",
            "",
            "# Goal",
        ]

        if self.session.goal:
            goal_json = self.session.goal.model_dump_json(indent=4)
            lines.append("GOAL = Goal.model_validate_json('''")
            lines.append(goal_json)
            lines.append("''')")
        else:
            lines.append("GOAL = None")

        lines.extend(
            [
                "",
                "",
                "# Nodes",
                "NODES = [",
            ]
        )

        for node in self.session.nodes:
            node_json = node.model_dump_json(indent=4)
            lines.append("    NodeSpec.model_validate_json('''")
            lines.append(node_json)
            lines.append("    '''),")

        lines.extend(
            [
                "]",
                "",
                "",
                "# Edges",
                "EDGES = [",
            ]
        )

        for edge in self.session.edges:
            edge_json = edge.model_dump_json(indent=4)
            lines.append("    EdgeSpec.model_validate_json('''")
            lines.append(edge_json)
            lines.append("    '''),")

        lines.extend(
            [
                "]",
                "",
                "",
                "# Graph",
            ]
        )

        graph_json = graph.model_dump_json(indent=4)
        lines.append("GRAPH = GraphSpec.model_validate_json('''")
        lines.append(graph_json)
        lines.append("''')")

        return "\n".join(lines)

    # =========================================================================
    # SESSION MANAGEMENT
    # =========================================================================

    def _require_phase(self, allowed: list[BuildPhase]) -> None:
        """Ensure we're in an allowed phase."""
        if self.session.phase not in allowed:
            raise RuntimeError(
                f"Cannot perform this action in phase '{self.session.phase.value}'. "
                f"Allowed phases: {[p.value for p in allowed]}"
            )

    def _save_session(self) -> None:
        """Save session to disk."""
        self.session.updated_at = datetime.now()
        path = self.storage_path / f"{self.session.id}.json"
        path.write_text(self.session.model_dump_json(indent=2))

    def _load_session(self, session_id: str) -> BuildSession:
        """Load session from disk."""
        path = self.storage_path / f"{session_id}.json"
        if not path.exists():
            raise FileNotFoundError(f"Session not found: {session_id}")
        return BuildSession.model_validate_json(path.read_text())

    @classmethod
    def list_sessions(cls, storage_path: Path | str | None = None) -> list[str]:
        """List all saved sessions."""
        path = Path(storage_path) if storage_path else Path.home() / ".core" / "builds"
        if not path.exists():
            return []
        return [f.stem for f in path.glob("*.json")]

    # =========================================================================
    # STATUS
    # =========================================================================

    def status(self) -> dict[str, Any]:
        """Get current build status."""
        return {
            "session_id": self.session.id,
            "name": self.session.name,
            "phase": self.session.phase.value,
            "goal": self.session.goal.name if self.session.goal else None,
            "nodes": len(self.session.nodes),
            "edges": len(self.session.edges),
            "tests": len(self.session.test_cases),
            "tests_passed": sum(1 for t in self.session.test_results if t.passed),
            "approvals": len(self.session.approvals),
            "pending_validation": self._pending_validation.model_dump()
            if self._pending_validation
            else None,
        }

    def show(self) -> str:
        """Show current graph as text."""
        lines = [
            f"=== Build: {self.session.name} ===",
            f"Phase: {self.session.phase.value}",
            "",
        ]

        if self.session.goal:
            lines.extend(
                [
                    f"Goal: {self.session.goal.name}",
                    f"  {self.session.goal.description}",
                    "",
                ]
            )

        if self.session.nodes:
            lines.append("Nodes:")
            for node in self.session.nodes:
                lines.append(f"  [{node.id}] {node.name} ({node.node_type})")
            lines.append("")

        if self.session.edges:
            lines.append("Edges:")
            for edge in self.session.edges:
                lines.append(f"  {edge.source} --{edge.condition.value}--> {edge.target}")
            lines.append("")

        if self._pending_validation:
            lines.append("Pending Validation:")
            lines.append(f"  Valid: {self._pending_validation.valid}")
            for err in self._pending_validation.errors:
                lines.append(f"  ERROR: {err}")
            for warn in self._pending_validation.warnings:
                lines.append(f"  WARN: {warn}")

        return "\n".join(lines)
