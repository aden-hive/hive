"""Tests for the Aden Hive Eval System."""

from __future__ import annotations
import pytest
import sys, os

# Direct import for testing
sys.path.insert(0, "/content/hive")
from core.framework.eval.eval import (
    BatchEvalReport, CriterionResult, EvalCriteria, EvalReport,
    EvalRunner, EvalSuite, FailureRecord, action_performed,
    contains_keyword, latency_under, no_error, output_not_empty,
)

class TestEvalCriteria:
    def test_basic_creation(self):
        c = EvalCriteria("has_output", "Output must exist", lambda r: bool(r.get("output")))
        assert c.name == "has_output"
        assert c.weight == 1.0
        assert c.required is False

class TestEvalSuite:
    def test_add_criterion(self):
        s = EvalSuite("test")
        s.add(EvalCriteria("a", "desc", lambda r: True))
        assert len(s) == 1

class TestEvalRunner:
    def _make_suite(self, threshold: float = 0.5) -> EvalSuite:
        s = EvalSuite("test", pass_threshold=threshold)
        s.add(EvalCriteria("has_output", "Output not empty", lambda r: bool(r.get("output"))))
        s.add(EvalCriteria("no_errors", "No error key", lambda r: "error" not in r))
        return s

    def test_all_pass(self):
        runner = EvalRunner(self._make_suite())
        report = runner.evaluate({"output": "hello"})
        assert report.passed is True
        assert report.score == 1.0

    def test_all_fail(self):
        runner = EvalRunner(self._make_suite(threshold=0.5))
        report = runner.evaluate({"error": "boom"})
        assert report.passed is False
        assert report.failure_record is not None

class TestBatchEvalReport:
    def test_pass_rate(self):
        s = EvalSuite("batch_test", pass_threshold=0.5)
        s.add(EvalCriteria("has_output", "desc", lambda r: bool(r.get("output"))))
        runner = EvalRunner(s)
        batch = runner.evaluate_batch([{"output": "hi"}, {"output": ""}, {"output": "ok"}])
        assert batch.pass_rate == pytest.approx(2 / 3)

class TestBuiltinCriteria:
    def test_output_not_empty_fails(self):
        c = output_not_empty()
        assert c.check({"output": ""}) is False
