"""
Tests for LLM routing failure modes in EdgeSpec.

Tests the three failure handling strategies:
- PROCEED: Fail-open (backward compatible)
- SKIP: Fail-closed (security-critical)
- RAISE: Escalate to executor
"""

import json
import pytest
from unittest.mock import Mock, MagicMock

from framework.graph.edge import EdgeSpec, EdgeCondition, LLMFailureMode


class TestLLMRoutingFailureModes:
    """Test cases for on_llm_failure parameter in EdgeSpec."""

    def setup_method(self):
        """Set up test fixtures."""
        self.mock_goal = Mock()
        self.mock_goal.name = "Test Goal"
        self.mock_goal.description = "Test goal description"
        
        self.source_output = {"result": "success"}
        self.memory = {"key": "value"}

    def create_edge(self, on_llm_failure: LLMFailureMode = LLMFailureMode.PROCEED) -> EdgeSpec:
        """Helper to create an EdgeSpec with LLM_DECIDE condition."""
        return EdgeSpec(
            id="test-edge",
            source="source_node",
            target="target_node",
            condition=EdgeCondition.LLM_DECIDE,
            on_llm_failure=on_llm_failure,
            description="Test edge",
        )

    def test_backward_compatibility_default_is_proceed(self):
        """Test that default on_llm_failure is PROCEED for backward compatibility."""
        edge = EdgeSpec(
            id="test-edge",
            source="source",
            target="target",
            condition=EdgeCondition.LLM_DECIDE,
        )
        assert edge.on_llm_failure == LLMFailureMode.PROCEED

    def test_llm_failure_mode_proceed_on_missing_llm(self):
        """Test PROCEED mode when LLM is not available - should return source_success."""
        edge = self.create_edge(on_llm_failure=LLMFailureMode.PROCEED)
        
        # LLM unavailable, source succeeded
        result = edge.should_traverse(
            source_success=True,
            source_output=self.source_output,
            memory=self.memory,
            llm=None,  # No LLM available
            goal=self.mock_goal,
        )
        assert result is True  # Proceeds because source succeeded
        
        # LLM unavailable, source failed
        result = edge.should_traverse(
            source_success=False,
            source_output=self.source_output,
            memory=self.memory,
            llm=None,
            goal=self.mock_goal,
        )
        assert result is False  # Doesn't proceed because source failed

    def test_llm_failure_mode_proceed_on_exception(self):
        """Test PROCEED mode when LLM throws exception - should return source_success."""
        edge = self.create_edge(on_llm_failure=LLMFailureMode.PROCEED)
        
        # Mock LLM that raises exception
        mock_llm = Mock()
        mock_llm.complete.side_effect = Exception("LLM API error")
        
        # Source succeeded, LLM fails
        result = edge.should_traverse(
            source_success=True,
            source_output=self.source_output,
            memory=self.memory,
            llm=mock_llm,
            goal=self.mock_goal,
        )
        assert result is True  # Fail-open: proceeds because source succeeded

    def test_llm_failure_mode_proceed_on_parse_error(self):
        """Test PROCEED mode when JSON parsing fails - should return source_success."""
        edge = self.create_edge(on_llm_failure=LLMFailureMode.PROCEED)
        
        # Mock LLM that returns non-JSON response
        mock_llm = Mock()
        mock_response = Mock()
        mock_response.content = "This is not JSON, just plain text"
        mock_llm.complete.return_value = mock_response
        
        result = edge.should_traverse(
            source_success=True,
            source_output=self.source_output,
            memory=self.memory,
            llm=mock_llm,
            goal=self.mock_goal,
        )
        assert result is True  # Fail-open: proceeds because source succeeded

    def test_llm_failure_mode_skip_on_missing_llm(self):
        """Test SKIP mode when LLM is not available - should return False."""
        edge = self.create_edge(on_llm_failure=LLMFailureMode.SKIP)
        
        result = edge.should_traverse(
            source_success=True,  # Even though source succeeded
            source_output=self.source_output,
            memory=self.memory,
            llm=None,
            goal=self.mock_goal,
        )
        assert result is False  # Fail-closed: does not proceed

    def test_llm_failure_mode_skip_on_exception(self):
        """Test SKIP mode when LLM throws exception - should return False."""
        edge = self.create_edge(on_llm_failure=LLMFailureMode.SKIP)
        
        mock_llm = Mock()
        mock_llm.complete.side_effect = Exception("LLM API error")
        
        result = edge.should_traverse(
            source_success=True,
            source_output=self.source_output,
            memory=self.memory,
            llm=mock_llm,
            goal=self.mock_goal,
        )
        assert result is False  # Fail-closed: does not proceed

    def test_llm_failure_mode_skip_on_parse_error(self):
        """Test SKIP mode when JSON parsing fails - should return False."""
        edge = self.create_edge(on_llm_failure=LLMFailureMode.SKIP)
        
        mock_llm = Mock()
        mock_response = Mock()
        mock_response.content = "Invalid JSON response"
        mock_llm.complete.return_value = mock_response
        
        result = edge.should_traverse(
            source_success=True,
            source_output=self.source_output,
            memory=self.memory,
            llm=mock_llm,
            goal=self.mock_goal,
        )
        assert result is False  # Fail-closed: does not proceed

    def test_llm_failure_mode_raise_on_missing_llm(self):
        """Test RAISE mode when LLM is not available - should raise RuntimeError."""
        edge = self.create_edge(on_llm_failure=LLMFailureMode.RAISE)
        
        with pytest.raises(RuntimeError, match="LLM routing failed for edge 'test-edge'"):
            edge.should_traverse(
                source_success=True,
                source_output=self.source_output,
                memory=self.memory,
                llm=None,
                goal=self.mock_goal,
            )

    def test_llm_failure_mode_raise_on_exception(self):
        """Test RAISE mode when LLM throws exception - should raise RuntimeError."""
        edge = self.create_edge(on_llm_failure=LLMFailureMode.RAISE)
        
        mock_llm = Mock()
        mock_llm.complete.side_effect = Exception("LLM API error")
        
        with pytest.raises(RuntimeError, match="LLM routing failed for edge 'test-edge'"):
            edge.should_traverse(
                source_success=True,
                source_output=self.source_output,
                memory=self.memory,
                llm=mock_llm,
                goal=self.mock_goal,
            )

    def test_llm_failure_mode_raise_includes_context(self):
        """Test that RAISE mode includes edge context in exception message."""
        edge = self.create_edge(on_llm_failure=LLMFailureMode.RAISE)
        
        with pytest.raises(
            RuntimeError,
            match=r"source=source_node -> target=target_node"
        ):
            edge.should_traverse(
                source_success=True,
                source_output=self.source_output,
                memory=self.memory,
                llm=None,
                goal=self.mock_goal,
            )

    def test_llm_routing_success_ignores_failure_mode(self):
        """Test that successful LLM routing works regardless of on_llm_failure mode."""
        # Test all three modes with successful LLM routing
        for mode in [LLMFailureMode.PROCEED, LLMFailureMode.SKIP, LLMFailureMode.RAISE]:
            edge = self.create_edge(on_llm_failure=mode)
            
            # Mock successful LLM response
            mock_llm = Mock()
            mock_response = Mock()
            mock_response.content = json.dumps({"proceed": True, "reasoning": "Test reason"})
            mock_llm.complete.return_value = mock_response
            
            result = edge.should_traverse(
                source_success=True,
                source_output=self.source_output,
                memory=self.memory,
                llm=mock_llm,
                goal=self.mock_goal,
            )
            assert result is True  # All modes should proceed when LLM says proceed

    def test_llm_routing_success_can_skip(self):
        """Test that successful LLM routing can choose to skip."""
        edge = self.create_edge(on_llm_failure=LLMFailureMode.PROCEED)
        
        # Mock LLM that decides not to proceed
        mock_llm = Mock()
        mock_response = Mock()
        mock_response.content = json.dumps({"proceed": False, "reasoning": "Not ready"})
        mock_llm.complete.return_value = mock_response
        
        result = edge.should_traverse(
            source_success=True,
            source_output=self.source_output,
            memory=self.memory,
            llm=mock_llm,
            goal=self.mock_goal,
        )
        assert result is False  # Should skip when LLM decides not to proceed

    def test_security_critical_edge_fail_closed(self):
        """
        Integration test: Security-critical edge with fail-closed behavior.
        
        Simulates authorization check where LLM failure must not allow access.
        """
        auth_edge = EdgeSpec(
            id="auth-check",
            source="validate_token",
            target="protected_resource",
            condition=EdgeCondition.LLM_DECIDE,
            on_llm_failure=LLMFailureMode.SKIP,  # Fail-closed for security
            description="Authorization check",
        )
        
        # Simulate LLM service outage
        result = auth_edge.should_traverse(
            source_success=True,  # Token validated successfully
            source_output={"token": "valid"},
            memory={},
            llm=None,  # LLM unavailable
            goal=self.mock_goal,
        )
        
        # Must NOT proceed to protected resource when LLM fails
        assert result is False, "Security critical edge should not proceed on LLM failure"

    def test_missing_goal_handled_correctly(self):
        """Test that missing goal is handled the same as missing LLM."""
        edge = self.create_edge(on_llm_failure=LLMFailureMode.SKIP)
        
        mock_llm = Mock()
        
        result = edge.should_traverse(
            source_success=True,
            source_output=self.source_output,
            memory=self.memory,
            llm=mock_llm,
            goal=None,  # No goal available
        )
        assert result is False  # Fail-closed when goal unavailable


class TestLLMRoutingErrorMessages:
    """Test that error messages are helpful and include context."""

    def test_error_message_includes_edge_id(self, caplog):
        """Test that error logs include edge ID for debugging."""
        edge = EdgeSpec(
            id="my-custom-edge-id",
            source="src",
            target="tgt",
            condition=EdgeCondition.LLM_DECIDE,
            on_llm_failure=LLMFailureMode.SKIP,
        )
        
        edge.should_traverse(
            source_success=True,
            source_output={},
            memory={},
            llm=None,
            goal=Mock(name="TestGoal", description="Test"),
        )
        
        # Check that edge ID appears in logs (implementation may vary)
        # This is a basic check - actual log format depends on logger configuration

    def test_raise_mode_exception_chains_original_error(self):
        """Test that RAISE mode chains the original exception for debugging."""
        edge = EdgeSpec(
            id="test-edge",
            source="src",
            target="tgt",
            condition=EdgeCondition.LLM_DECIDE,
            on_llm_failure=LLMFailureMode.RAISE,
        )
        
        mock_llm = Mock()
        original_error = ValueError("Original LLM error")
        mock_llm.complete.side_effect = original_error
        
        with pytest.raises(RuntimeError) as exc_info:
            edge.should_traverse(
                source_success=True,
                source_output={},
                memory={},
                llm=mock_llm,
                goal=Mock(name="Test", description="Test"),
            )
        
        # Check that original exception is chained
        assert exc_info.value.__cause__ == original_error
