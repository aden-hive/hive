"""Tests for ChatTextArea key handling (Enter submits, Shift+Enter / Ctrl+J insert newlines)."""

import pytest
from textual.app import App, ComposeResult

from framework.tui.widgets.chat_repl import ChatTextArea


class ChatTextAreaApp(App):
    """Minimal app that mounts a ChatTextArea for testing."""

    submitted_texts: list[str]

    def compose(self) -> ComposeResult:
        yield ChatTextArea(id="input")

    def on_mount(self) -> None:
        self.submitted_texts = []

    def on_chat_text_area_submitted(self, message: ChatTextArea.Submitted) -> None:
        self.submitted_texts.append(message.text)


@pytest.fixture
def app():
    return ChatTextAreaApp()


@pytest.mark.asyncio
async def test_enter_submits_text(app):
    """Pressing Enter should post a Submitted message and clear the widget."""
    async with app.run_test() as pilot:
        await pilot.press("h", "e", "l", "l", "o")
        await pilot.press("enter")

    assert app.submitted_texts == ["hello"]


@pytest.mark.asyncio
async def test_enter_on_empty_does_not_submit(app):
    """Pressing Enter with no text should not post a Submitted message."""
    async with app.run_test() as pilot:
        await pilot.press("enter")

    assert app.submitted_texts == []


@pytest.mark.asyncio
async def test_shift_enter_inserts_newline(app):
    """Shift+Enter should insert a newline, not submit."""
    async with app.run_test() as pilot:
        widget = app.query_one("#input", ChatTextArea)

        await pilot.press("a")
        await pilot.press("shift+enter")
        await pilot.press("b")

    assert app.submitted_texts == []
    assert "\n" in widget.text
    assert widget.text.startswith("a")
    assert widget.text.endswith("b")


@pytest.mark.asyncio
async def test_ctrl_j_inserts_newline(app):
    """Ctrl+J should insert a newline (fallback for terminals without Shift+Enter)."""
    async with app.run_test() as pilot:
        widget = app.query_one("#input", ChatTextArea)

        await pilot.press("a")
        await pilot.press("ctrl+j")
        await pilot.press("b")

    assert app.submitted_texts == []
    assert "\n" in widget.text
    assert widget.text.startswith("a")
    assert widget.text.endswith("b")


@pytest.mark.asyncio
async def test_multiline_submit(app):
    """Typing multiline text via Ctrl+J then pressing Enter should submit all lines."""
    async with app.run_test() as pilot:
        await pilot.press("a")
        await pilot.press("ctrl+j")
        await pilot.press("b")
        await pilot.press("enter")

    assert len(app.submitted_texts) == 1
    assert app.submitted_texts[0] == "a\nb"
