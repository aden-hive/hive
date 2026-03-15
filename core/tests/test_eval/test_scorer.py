"""Unit tests for EvalScorer."""
import pytest
from framework.eval.case import EvalCase, EvalExpectation
from framework.eval.scorer import EvalScorer, ScorerConfig


@pytest.fixture
def scorer():
    return EvalScorer(ScorerConfig(use_llm_judge=False))


def make_case(expect_kwargs) -> EvalCase:
    return EvalCase(id="test_case", input={"message": "hello"}, expect=EvalExpectation(**expect_kwargs))


def test_contains_pass(scorer):
    result = scorer.score(make_case({"contains": ["hello"]}), "hello world", None, 100, 0.0, [], [])
    assert result.passed and result.score == 1.0

def test_contains_fail(scorer):
    result = scorer.score(make_case({"contains": ["missing"]}), "hello world", None, 100, 0.0, [], [])
    assert not result.passed

def test_not_contains_pass(scorer):
    result = scorer.score(make_case({"not_contains": ["forbidden"]}), "clean output", None, 100, 0.0, [], [])
    assert result.passed

def test_not_contains_fail(scorer):
    result = scorer.score(make_case({"not_contains": ["forbidden"]}), "has forbidden word", None, 100, 0.0, [], [])
    assert not result.passed

def test_exact_match_pass(scorer):
    result = scorer.score(make_case({"exact_match": "exact output"}), "exact output", None, 100, 0.0, [], [])
    assert result.passed

def test_exact_match_fail(scorer):
    result = scorer.score(make_case({"exact_match": "exact output"}), "different", None, 100, 0.0, [], [])
    assert not result.passed

def test_unexpected_error_fails(scorer):
    result = scorer.score(make_case({}), None, "something broke", 100, 0.0, [], [])
    assert not result.passed and result.score == 0.0

def test_expected_error_passes(scorer):
    result = scorer.score(make_case({"error": True}), None, "expected failure", 100, 0.0, [], [])
    assert result.passed and result.score == 1.0

def test_latency_pass(scorer):
    result = scorer.score(make_case({"max_latency_ms": 1000}), "output", None, 500, 0.0, [], [])
    assert result.passed

def test_latency_fail(scorer):
    result = scorer.score(make_case({"max_latency_ms": 500}), "output", None, 1000, 0.0, [], [])
    assert not result.passed

def test_required_tools_pass(scorer):
    result = scorer.score(make_case({"required_tools": ["search"]}), "output", None, 100, 0.0, ["search"], [])
    assert result.passed

def test_required_tools_fail(scorer):
    result = scorer.score(make_case({"required_tools": ["search"]}), "output", None, 100, 0.0, [], [])
    assert not result.passed

def test_max_tools_pass(scorer):
    result = scorer.score(make_case({"max_tools_called": 2}), "output", None, 100, 0.0, ["a", "b"], [])
    assert result.passed

def test_max_tools_fail(scorer):
    result = scorer.score(make_case({"max_tools_called": 1}), "output", None, 100, 0.0, ["a", "b", "c"], [])
    assert not result.passed

def test_cost_pass(scorer):
    result = scorer.score(make_case({"max_cost_usd": 0.01}), "output", None, 100, 0.001, [], [])
    assert result.passed

def test_cost_fail(scorer):
    result = scorer.score(make_case({"max_cost_usd": 0.001}), "output", None, 100, 0.01, [], [])
    assert not result.passed

def test_empty_expectations_pass(scorer):
    result = scorer.score(make_case({}), "anything", None, 100, 0.0, [], [])
    assert result.passed and result.score == 1.0
