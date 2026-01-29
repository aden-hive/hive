import pytest

from framework.graph.output_cleaner import CleansingConfig, OutputCleaner


class DummyNodeSpec:
    id = "dummy"
    input_keys = ["result"]
    input_schema = {"result": {"type": "string"}}


class DummyLLMResponse:
    def __init__(self, content):
        self.content = content


class DummyLLM:
    def __init__(self, content):
        self._content = content

    def complete(self, *args, **kwargs):
        return DummyLLMResponse(self._content)


def test_validate_output_rejects_non_dict_output():
    cleaner = OutputCleaner(CleansingConfig(enabled=False), llm_provider=None)
    node_spec = DummyNodeSpec()

    res = cleaner.validate_output(None, "source", node_spec)
    assert res.valid is False
    assert "Output must be dict" in res.errors[0]


def test_clean_output_handles_none_response_content_with_fallback():
    cfg = CleansingConfig(enabled=True, fallback_to_raw=True, log_cleanings=False)
    cleaner = OutputCleaner(cfg, llm_provider=DummyLLM(None))
    node_spec = DummyNodeSpec()

    raw_output = {"result": "bad-json"}
    cleaned = cleaner.clean_output(
        output=raw_output,
        source_node_id="source",
        target_node_spec=node_spec,
        validation_errors=["error"],
    )
    assert cleaned == raw_output


def test_clean_output_handles_whitespace_response_content_with_fallback():
    cfg = CleansingConfig(enabled=True, fallback_to_raw=True, log_cleanings=False)
    cleaner = OutputCleaner(cfg, llm_provider=DummyLLM("   "))
    node_spec = DummyNodeSpec()

    raw_output = {"result": "bad-json"}
    cleaned = cleaner.clean_output(
        output=raw_output,
        source_node_id="source",
        target_node_spec=node_spec,
        validation_errors=["error"],
    )
    assert cleaned == raw_output


def test_clean_output_raises_on_empty_response_without_fallback():
    cfg = CleansingConfig(enabled=True, fallback_to_raw=False, log_cleanings=False)
    cleaner = OutputCleaner(cfg, llm_provider=DummyLLM(""))
    node_spec = DummyNodeSpec()

    raw_output = {"result": "bad-json"}

    with pytest.raises(ValueError):
        cleaner.clean_output(
            output=raw_output,
            source_node_id="source",
            target_node_spec=node_spec,
            validation_errors=["error"],
        )
