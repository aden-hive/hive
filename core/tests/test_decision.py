import pytest
from datetime import datetime

from framework.schemas.decision import (
    Decision, 
    Option, 
    Outcome, 
    DecisionEvaluation, 
    DecisionType
)

class TestDecision:
    """Test the Decision class."""
    def test_chosen_option_found(self):
        """Test retrieving the chosen option when it exists."""
        opt1 = Option(id="opt1", description="Option 1", action_type="generate")
        opt2 = Option(id="opt2", description="Option 2", action_type="generate")
        
        decision = Decision(
            id="d1",
            node_id="node1",
            intent="Test intent",
            options=[opt1, opt2],
            chosen_option_id="opt2"
        )
        
        assert decision.chosen_option == opt2
        assert decision.chosen_option.id == "opt2"

    def test_chosen_option_none(self):
        """Test retrieving chosen option returns none when not found."""
        opt1 = Option(id="opt1", description="Option 1", action_type="generate")
        
        decision = Decision(
            id="d1",
            node_id="node1",
            intent="Test intent",
            options=[opt1],
            chosen_option_id="opt_nonexistent"
        )
        
        assert decision.chosen_option is None

    def test_was_successful_true(self):
        """Test was_successful returns true for successful outcome."""
        decision = Decision(
            id="d1",
            node_id="node1",
            intent="Test intent",
            options=[],
            outcome=Outcome(success=True)
        )
        
        assert decision.was_successful is True

    def test_was_successful_false(self):
        """Test was_successful returns False for failed outcome."""
        decision = Decision(
            id="d1",
            node_id="node1",
            intent="Test intent",
            options=[],
            outcome=Outcome(success=False, error="Failed")
        )
        
        assert decision.was_successful is False

    def test_was_successful_no_outcome(self):
        """Test was_successful returns False when no outcome exists."""
        decision = Decision(
            id="d1",
            node_id="node1",
            intent="Test intent",
            options=[]
        )
        
        assert decision.was_successful is False

    def test_was_good_decision_no_eval(self):
        """Test was_good_decision falls back to success status when no evaluation."""
        # successful case
        d1 = Decision(
            id="d1",
            node_id="node1",
            intent="Test intent",
            outcome=Outcome(success=True)
        )
        assert d1.was_good_decision is True

        # failing case
        d2 = Decision(
            id="d2",
            node_id="node1",
            intent="Test intent",
            outcome=Outcome(success=False)
        )
        assert d2.was_good_decision is False

    def test_was_good_decision_eval_good(self):
        """Test was_good_decision returns True for good evaluation."""
        decision = Decision(
            id="d1",
            node_id="node1",
            intent="Test intent",
            evaluation=DecisionEvaluation(
                goal_aligned=True,
                outcome_quality=0.8
            )
        )
        assert decision.was_good_decision is True

    def test_was_good_decision_eval_bad_alignment(self):
        """Test was_good_decision returns False if not goal aligned."""
        decision = Decision(
            id="d1",
            node_id="node1",
            intent="Test intent",
            evaluation=DecisionEvaluation(
                goal_aligned=False,
                outcome_quality=0.9
            )
        )
        assert decision.was_good_decision is False

    def test_was_good_decision_eval_bad_quality(self):
        """Test was_good_decision returns False if quality is low."""
        decision = Decision(
            id="d1",
            node_id="node1",
            intent="Test intent",
            evaluation=DecisionEvaluation(
                goal_aligned=True,
                outcome_quality=0.4
            )
        )
        assert decision.was_good_decision is False

    def test_summary_for_builder_success(self):
        """Test summary string for successful decision."""
        opt = Option(id="opt1", description="Do magic", action_type="generate")
        decision = Decision(
            id="d1",
            node_id="gen_node",
            intent="Generate code",
            options=[opt],
            chosen_option_id="opt1",
            outcome=Outcome(success=True)
        )
        
        summary = decision.summary_for_builder()
        assert "✓ [gen_node] Generate code → Do magic" in summary
        assert "quality" not in summary

    def test_summary_for_builder_failure(self):
        """Test summary string for failed decision."""
        opt = Option(id="opt1", description="Do magic", action_type="generate")
        decision = Decision(
            id="d1",
            node_id="gen_node",
            intent="Generate code",
            options=[opt],
            chosen_option_id="opt1",
            outcome=Outcome(success=False)
        )
        
        summary = decision.summary_for_builder()
        assert "✗ [gen_node] Generate code → Do magic" in summary

    def test_summary_for_builder_with_eval(self):
        """Test summary string includes quality when available."""
        opt = Option(id="opt1", description="Do magic", action_type="generate")
        decision = Decision(
            id="d1",
            node_id="gen_node",
            intent="Generate code",
            options=[opt],
            chosen_option_id="opt1",
            outcome=Outcome(success=True),
            evaluation=DecisionEvaluation(goal_aligned=True, outcome_quality=0.9)
        )
        
        summary = decision.summary_for_builder()
        assert "quality: 0.9" in summary