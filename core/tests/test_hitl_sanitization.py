import pytest

from framework.graph.conversation import NodeConversation
from framework.graph.event_loop_node import EventLoopNode, LoopConfig


@pytest.mark.asyncio
async def test_hitl_input_sanitization():
    # Setup node and conversation
    config = LoopConfig(max_user_input_chars=10)
    node = EventLoopNode(config=config)
    conv = NodeConversation()

    # Inject short message
    node._injection_queue.put_nowait(("hello", True))
    await node._drain_injection_queue(conv)

    assert conv.message_count == 1
    assert conv.messages[0].content == "<user_input>\nhello\n</user_input>"
    assert conv.messages[0].is_client_input is True


@pytest.mark.asyncio
async def test_hitl_input_truncation():
    # Setup node and conversation with small limit
    config = LoopConfig(max_user_input_chars=5)
    node = EventLoopNode(config=config)
    conv = NodeConversation()

    # Inject long message
    node._injection_queue.put_nowait(("1234567890", True))
    await node._drain_injection_queue(conv)

    assert conv.message_count == 1
    content = conv.messages[0].content
    assert "12345" in content
    assert "truncated to 5 chars" in content
    assert content.startswith("<user_input>")
    assert content.endswith("</user_input>")


@pytest.mark.asyncio
async def test_external_event_unsanitized():
    # External events should NOT be wrapped in <user_input> tags
    config = LoopConfig()
    node = EventLoopNode(config=config)
    conv = NodeConversation()

    node._injection_queue.put_nowait(("external trigger", False))
    await node._drain_injection_queue(conv)

    assert conv.message_count == 1
    assert conv.messages[0].content == "[External event]: external trigger"
    assert conv.messages[0].is_client_input is False
