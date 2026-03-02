from unittest.mock import MagicMock

import pytest

# We need to test the logic of ChatRepl without necessarily mounting a full Textual app.
# Textual widgets usually look up their app via the DOM.
# For a simple unit test, we can mock the property or use a patch.
from framework.tui.widgets.chat_repl import ChatRepl


@pytest.mark.asyncio
async def test_handle_command_agents():
    mock_runtime = MagicMock()
    repl = ChatRepl(mock_runtime)

    # Mock the 'app' property on the repl object
    mock_app = MagicMock()
    mock_app.action_show_agent_picker = MagicMock()

    # Using PropertyMock to mock the 'app' property of the widget
    from unittest.mock import PropertyMock, patch

    with patch(
        "framework.tui.widgets.chat_repl.ChatRepl.app", new_callable=PropertyMock
    ) as mock_app_prop:
        mock_app_prop.return_value = mock_app

        # Calling the command
        await repl._handle_command("/agents")

        # Verify the sync action was called successfully and didn't crash
        mock_app.action_show_agent_picker.assert_called_once()
