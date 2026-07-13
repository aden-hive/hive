import pytest
from pydantic import ValidationError

from framework.agent_loop.types import AgentSpec
from framework.orchestrator.node import NodeSpec


@pytest.fixture(params=[NodeSpec, AgentSpec], ids=["node", "agent"])
def spec_type(request):
    return request.param


def make_spec(spec_type, **overrides):
    values = {
        "id": "test",
        "name": "Test",
        "description": "Test spec",
    }
    values.update(overrides)
    return spec_type(**values)


def test_valid_output_keys(spec_type):
    spec = make_spec(
        spec_type,
        output_keys=["a", "b"],
        nullable_output_keys=["a"],
    )

    assert spec.output_keys == ["a", "b"]
    assert spec.nullable_output_keys == ["a"]


def test_duplicate_output_keys_raise(spec_type):
    with pytest.raises(ValidationError, match=r"output_keys contains duplicate keys: \['b', 'a'\]"):
        make_spec(spec_type, output_keys=["b", "a", "a", "b"])


def test_duplicate_nullable_output_keys_raise(spec_type):
    with pytest.raises(ValidationError, match=r"nullable_output_keys contains duplicate keys: \['a'\]"):
        make_spec(
            spec_type,
            output_keys=["a"],
            nullable_output_keys=["a", "a"],
        )


@pytest.mark.parametrize("blank_key", ["", "   "])
def test_empty_or_whitespace_only_output_keys_raise(spec_type, blank_key):
    with pytest.raises(ValidationError, match="output_keys contains empty or whitespace-only keys"):
        make_spec(spec_type, output_keys=[blank_key])


@pytest.mark.parametrize("blank_key", ["", "   "])
def test_empty_or_whitespace_only_nullable_output_keys_raise(spec_type, blank_key):
    with pytest.raises(ValidationError, match="nullable_output_keys contains empty or whitespace-only keys"):
        make_spec(spec_type, nullable_output_keys=[blank_key])


def test_orphan_nullable_output_keys_raise(spec_type):
    with pytest.raises(
        ValidationError,
        match=r"nullable_output_keys contains keys not present in output_keys: \['missing'\]",
    ):
        make_spec(
            spec_type,
            output_keys=["a"],
            nullable_output_keys=["missing"],
        )
