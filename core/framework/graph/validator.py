
from typing import List, Dict, Any, Set
import logging
from dataclasses import dataclass
from pydantic import BaseModel, ValidationError

logger = logging.getLogger(__name__)


@dataclass
class ValidationResult:
    """Result of validating an output."""

    success: bool
    errors: list[str]

    def __bool__(self):
        return self.success


class GraphValidator:
    """
    Validates graph structure reliability.
    Prevents 'technical cornas' (infinite loops, disconnected nodes).
    """

    @staticmethod
    def validate(graph_spec: Any) -> ValidationResult:
        """
        Run all validation checks on a GraphSpec-like object.
        Expected object structure: 
        - nodes: list of NodeSpec (with 'id')
        - edges: list of EdgeSpec (with 'source', 'target')
        - entry_node: str
        """
        
        # 1. Integrity Check (Basic Fields)
        if not hasattr(graph_spec, "nodes") or not hasattr(graph_spec, "edges") or not hasattr(graph_spec, "entry_node"):
             return ValidationResult(success=False, errors=["GraphSpec missing required attributes (nodes, edges, entry_node)"])

        # Convert list-based spec to fast-lookup dicts
        node_ids = {n.id for n in graph_spec.nodes}
        adj_list = {n_id: [] for n_id in node_ids}
        
        for edge in graph_spec.edges:
            if edge.source not in node_ids:
                return ValidationResult(success=False, errors=[f"Edge references missing source node: {edge.source}"])
            if edge.target not in node_ids:
                return ValidationResult(success=False, errors=[f"Edge references missing target node: {edge.target}"])
            adj_list[edge.source].append(edge.target)

        # 2. Cycle Detection (DFS)
        # We assume directed graphs. A cycle is fatal for simple DAG agents, 
        # but some agents MAY want loops (Retry Loops). 
        # However, for Safety, we usually warn or error on unintended cycles.
        # For this implementation, we will act as a strict DAG enforcer to prevent infinite loops 
        # unless specifically annotated (future feature).
        
        # Checking for cycles using recursion stack
        visited = set()
        rec_stack = set()
        
        def has_cycle(u):
            visited.add(u)
            rec_stack.add(u)
            
            for v in adj_list[u]:
                if v not in visited:
                    if has_cycle(v):
                        return True
                elif v in rec_stack:
                    return True
            
            rec_stack.remove(u)
            return False

        # Check from entry node first (most important)
        if graph_spec.entry_node not in node_ids:
             return ValidationResult(success=False, errors=[f"Entry node '{graph_spec.entry_node}' not found in nodes"])
             
        # Full scan (in case of disconnected components that might be triggered async)
        # But actually, only reachable cycles matter usually? 
        # Let's scan all nodes to be safe.
        for node_id in node_ids:
            if node_id not in visited:
                if has_cycle(node_id):
                    return ValidationResult(success=False, errors=[f"Cycle detected involving node '{node_id}'"])

        # 3. Connectivity/Reachability (optional strictness)
        # Verify that all nodes are reachable from entry_node (BFS)
        # Disconnected islands are technically dead code.
        reachable = set()
        from collections import deque
        q = deque([graph_spec.entry_node])
        reachable.add(graph_spec.entry_node)
        
        while q:
            u = q.popleft()
            for v in adj_list[u]:
                if v not in reachable:
                    reachable.add(v)
                    q.append(v)
                    
        # Check against all nodes
        unreachable = node_ids - reachable
        # Note: "start" node might be isolated if we are mutating? 
        # For now, we Log Warn but maybe not Fail? 
        # User requested "Connectivity", let's fail if significant islands exist?
        # Let's return Valid but with warning logic handled by caller? 
        # No, simpler: Fail. Dead code is messy.
        if unreachable:
             return ValidationResult(success=False, errors=[f"Unreachable nodes detected: {unreachable}"])

        return ValidationResult(success=True, errors=[])


class OutputValidator:
    """
    Validates output from nodes against schema.
    Restored to maintain compatibility with GraphExecutor.
    """

    def _contains_code_indicators(self, value: str) -> bool:
        """
        Check for code patterns in a string using sampling for efficiency.

        For strings under 10KB, checks the entire content.
        For longer strings, samples at strategic positions to balance
        performance with detection accuracy.

        Args:
            value: The string to check for code indicators

        Returns:
            True if code indicators are found, False otherwise
        """
        code_indicators = [
            # Python
            "def ",
            "class ",
            "import ",
            "from ",
            "if __name__",
            "async def ",
            "await ",
            "try:",
            "except:",
            # JavaScript/TypeScript
            "function ",
            "const ",
            "let ",
            "=> {",
            "require(",
            "export ",
            # SQL
            "SELECT ",
            "INSERT ",
            "UPDATE ",
            "DELETE ",
            "DROP ",
            # HTML/Script injection
            "<script",
            "<?php",
            "<%",
        ]

        # For strings under 10KB, check the entire content
        if len(value) < 10000:
            return any(indicator in value for indicator in code_indicators)

        # For longer strings, sample at strategic positions
        sample_positions = [
            0,  # Start
            len(value) // 4,  # 25%
            len(value) // 2,  # 50%
            3 * len(value) // 4,  # 75%
            max(0, len(value) - 2000),  # Near end
        ]

        for pos in sample_positions:
            chunk = value[pos : pos + 2000]
            if any(indicator in chunk for indicator in code_indicators):
                return True

        return False

    def validate_output_keys(
        self,
        output: dict[str, Any],
        expected_keys: list[str],
        allow_empty: bool = False,
        nullable_keys: list[str] | None = None,
    ) -> ValidationResult:
        """
        Validate that all expected keys are present and non-empty.

        Args:
            output: The output dict to validate
            expected_keys: Keys that must be present
            allow_empty: If True, allow empty string values
            nullable_keys: Keys that are allowed to be None

        Returns:
            ValidationResult with success status and any errors
        """
        errors = []
        nullable_keys = nullable_keys or []

        if not isinstance(output, dict):
            return ValidationResult(
                success=False, errors=[f"Output is not a dict, got {type(output).__name__}"]
            )

        for key in expected_keys:
            if key not in output:
                errors.append(f"Missing required output key: '{key}'")
            elif not allow_empty:
                value = output[key]
                if value is None:
                    if key not in nullable_keys:
                        errors.append(f"Output key '{key}' is None")
                elif isinstance(value, str) and len(value.strip()) == 0:
                    errors.append(f"Output key '{key}' is empty string")

        return ValidationResult(success=len(errors) == 0, errors=errors)

    def validate_with_pydantic(
        self,
        output: dict[str, Any],
        model: type[BaseModel],
    ) -> tuple[ValidationResult, BaseModel | None]:
        """
        Validate output against a Pydantic model.

        Args:
            output: The output dict to validate
            model: Pydantic model class to validate against

        Returns:
            Tuple of (ValidationResult, validated_model_instance or None)
        """
        try:
            validated = model.model_validate(output)
            return ValidationResult(success=True, errors=[]), validated
        except ValidationError as e:
            errors = []
            for error in e.errors():
                field_path = ".".join(str(loc) for loc in error["loc"])
                msg = error["msg"]
                error_type = error["type"]
                errors.append(f"{field_path}: {msg} (type: {error_type})")
            return ValidationResult(success=False, errors=errors), None

    def format_validation_feedback(
        self,
        validation_result: ValidationResult,
        model: type[BaseModel],
    ) -> str:
        """
        Format validation errors as feedback for LLM retry.

        Args:
            validation_result: The failed validation result
            model: The Pydantic model that was used for validation

        Returns:
            Formatted feedback string to include in retry prompt
        """
        # Get the model's JSON schema for reference
        schema = model.model_json_schema()

        feedback = "Your previous response had validation errors:\n\n"
        feedback += "ERRORS:\n"
        for error in validation_result.errors:
            feedback += f"  - {error}\n"

        feedback += "\nEXPECTED SCHEMA:\n"
        feedback += f"  Model: {model.__name__}\n"

        if "properties" in schema:
            feedback += "  Required fields:\n"
            required = schema.get("required", [])
            for prop_name, prop_info in schema["properties"].items():
                req_marker = " (required)" if prop_name in required else ""
                prop_type = prop_info.get("type", "any")
                feedback += f"    - {prop_name}: {prop_type}{req_marker}\n"

        feedback += "\nPlease fix the errors and respond with valid JSON matching the schema."

        return feedback

    def validate_no_hallucination(
        self,
        output: dict[str, Any],
        max_length: int = 10000,
    ) -> ValidationResult:
        """
        Check for signs of LLM hallucination in output values.

        Detects:
        - Code blocks where structured data was expected
        - Overly long values that suggest raw LLM output
        - Common hallucination patterns

        Args:
            output: The output dict to validate
            max_length: Maximum allowed length for string values

        Returns:
            ValidationResult with success status and any errors
        """
        errors = []

        for key, value in output.items():
            if not isinstance(value, str):
                continue

            # Check for code patterns in the entire string, not just first 500 chars
            if self._contains_code_indicators(value):
                # Could be legitimate, but warn
                logger.warning(f"Output key '{key}' may contain code - verify this is expected")

            # Check for overly long values
            if len(value) > max_length:
                errors.append(
                    f"Output key '{key}' exceeds max length ({len(value)} > {max_length})"
                )

        return ValidationResult(success=len(errors) == 0, errors=errors)

    def validate_schema(
        self,
        output: dict[str, Any],
        schema: dict[str, Any],
    ) -> ValidationResult:
        """
        Validate output against a JSON schema.

        Args:
            output: The output dict to validate
            schema: JSON schema to validate against

        Returns:
            ValidationResult with success status and any errors
        """
        try:
            import jsonschema
        except ImportError:
            logger.warning("jsonschema not installed, skipping schema validation")
            return ValidationResult(success=True, errors=[])

        errors = []
        validator = jsonschema.Draft7Validator(schema)

        for error in validator.iter_errors(output):
            path = ".".join(str(p) for p in error.path) if error.path else "root"
            errors.append(f"{path}: {error.message}")

        return ValidationResult(success=len(errors) == 0, errors=errors)

    def validate_all(
        self,
        output: dict[str, Any],
        expected_keys: list[str] | None = None,
        schema: dict[str, Any] | None = None,
        check_hallucination: bool = True,
        nullable_keys: list[str] | None = None,
    ) -> ValidationResult:
        """
        Run all applicable validations on output.

        Args:
            output: The output dict to validate
            expected_keys: Optional list of required keys
            schema: Optional JSON schema
            check_hallucination: Whether to check for hallucination patterns
            nullable_keys: Keys that are allowed to be None

        Returns:
            Combined ValidationResult
        """
        all_errors = []

        # Validate keys if provided
        if expected_keys:
            result = self.validate_output_keys(output, expected_keys, nullable_keys=nullable_keys)
            all_errors.extend(result.errors)

        # Validate schema if provided
        if schema:
            result = self.validate_schema(output, schema)
            all_errors.extend(result.errors)

        # Check for hallucination
        if check_hallucination:
            result = self.validate_no_hallucination(output)
            all_errors.extend(result.errors)

        return ValidationResult(success=len(all_errors) == 0, errors=all_errors)
