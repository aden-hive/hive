import asyncio
from unittest.mock import MagicMock

import pytest

from framework.graph.output_cleaner import CleansingConfig, OutputCleaner


@pytest.mark.asyncio
async def test_clean_output_timeout():
    # Setup a mock LLM that hangs forever
    mock_llm = MagicMock()

    async def hang_forever(*args, **kwargs):
        await asyncio.sleep(10)
        return MagicMock(content="{}")

    mock_llm.acomplete = hang_forever

    # Config with short timeout
    config = CleansingConfig(timeout_seconds=0.1, fallback_to_raw=True)
    cleaner = OutputCleaner(config=config, llm_provider=mock_llm)

    raw_output = {"data": "malformed"}

    mock_spec = MagicMock()
    mock_spec.input_keys = []

    # Should timeout and return raw_output because fallback_to_raw=True
    result = await cleaner.clean_output(
        output=raw_output,
        source_node_id="test_node",
        target_node_spec=mock_spec,
        validation_errors=[],
    )

    assert result == raw_output


@pytest.mark.asyncio
async def test_clean_output_timeout_no_fallback():
    # Setup a mock LLM that hangs forever
    mock_llm = MagicMock()

    async def hang_forever(*args, **kwargs):
        await asyncio.sleep(10)
        return MagicMock(content="{}")

    mock_llm.acomplete = hang_forever

    # Config with short timeout and NO fallback
    config = CleansingConfig(timeout_seconds=0.1, fallback_to_raw=False)
    cleaner = OutputCleaner(config=config, llm_provider=mock_llm)

    raw_output = {"data": "malformed"}

    mock_spec = MagicMock()
    mock_spec.input_keys = []

    # Should raise TimeoutError (wrapped in asyncio.wait_for)
    with pytest.raises(asyncio.TimeoutError):
        await cleaner.clean_output(
            output=raw_output,
            source_node_id="test_node",
            target_node_spec=mock_spec,
            validation_errors=[],
        )
