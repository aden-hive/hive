"""Regression tests for edge-condition context precedence (issue #7380).

A buffer key that happens to share a reserved name (``result``/``true``/``false``/
``output``/``buffer``) must not shadow the framework builtins injected into the
condition-evaluation context, or conditional edges route on stale/incorrect values.
"""

from framework.orchestrator.edge import EdgeCondition, EdgeSpec


def _conditional_edge(expr: str) -> EdgeSpec:
    return EdgeSpec(
        id="e1",
        source="a",
        target="b",
        condition=EdgeCondition.CONDITIONAL,
        condition_expr=expr,
    )


def test_result_builtin_not_shadowed_by_stale_buffer():
    """`result` resolves to the current output, not a stale buffer value (issue #7380)."""
    edge = _conditional_edge("result == 'NEW'")
    # Buffer still holds the previous node's result; the builtin must win.
    assert edge._evaluate_condition({"result": "NEW"}, {"result": "OLD"}) is True


def test_true_false_builtins_not_shadowed_by_buffer():
    """Buffer keys named true/false cannot override the boolean builtins."""
    edge_true = _conditional_edge("true")
    assert edge_true._evaluate_condition({}, {"true": False}) is True

    edge_false = _conditional_edge("false")
    assert edge_false._evaluate_condition({}, {"false": True}) is False


def test_non_reserved_buffer_keys_remain_accessible():
    """Buffer keys that don't collide with a builtin are still usable in conditions."""
    edge = _conditional_edge("score > 3")
    assert edge._evaluate_condition({}, {"score": 5}) is True
    assert edge._evaluate_condition({}, {"score": 1}) is False
