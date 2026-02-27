import pytest

from framework.runtime.execution_trace import ExecutionTrace


def test_span_nesting_parent_child_relationships():
    trace = ExecutionTrace()

    with trace.span("root") as root_span:
        with trace.span("child") as child_span:
            assert child_span.parent_id == root_span.id

    spans = trace.spans
    assert len(spans) == 2

    root_children = trace.children(root_span.id)
    assert len(root_children) == 1
    assert root_children[0].id == child_span.id


def test_span_ordering_is_deterministic():
    trace = ExecutionTrace()

    with trace.span("first"):
        pass
    with trace.span("second"):
        pass
    with trace.span("third"):
        pass

    payload = trace.to_dict()
    ordered_names = [span["name"] for span in payload["spans"]]
    assert ordered_names == ["first", "second", "third"]


def test_span_exception_sets_error_status_and_metadata():
    trace = ExecutionTrace()

    with pytest.raises(ValueError):
        with trace.span("fails"):
            raise ValueError("boom")

    payload = trace.to_dict()
    assert len(payload["spans"]) == 1

    span = payload["spans"][0]
    assert span["status"] == "error"
    assert span["metadata"]["exception_type"] == "ValueError"
    assert span["metadata"]["exception_message"] == "boom"
