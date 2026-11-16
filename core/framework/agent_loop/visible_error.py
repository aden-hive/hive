"""The text a queen's chat shows when a model call fails.

The agent loop writes it as her reply when a call fails, and the dashboard renders it as an error
card. A gateway that is itself built on Hive can return the same text as an ordinary completion when
its upstream fails, so it can reach the loop as model output too: whoever forwards or judges her
replies should recognise it either way.
"""

PREFIX = "[Error: LLM call failed: "


def visible_error(error_msg: str) -> str:
    """``error_msg`` starts with ``"LLM call failed: "``."""
    return f"[Error: {error_msg}. Please try again.]"


def is_visible_error(text: str) -> bool:
    return text.lstrip().startswith(PREFIX)
