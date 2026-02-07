"""JSON utilities for node operations.

These utilities help with parsing and extracting JSON from LLM responses
which may contain markdown code blocks, unescaped characters, or other wrapper content.
"""


def fix_unescaped_newlines_in_json(json_str: str) -> str:
    """Fix unescaped newlines inside JSON string values.

    LLMs sometimes output actual newlines inside JSON strings instead of \\n.
    This function fixes that by properly escaping newlines within string values.

    Args:
        json_str: The JSON string that may contain unescaped newlines.

    Returns:
        The JSON string with properly escaped newlines within string values.
    """
    result = []
    in_string = False
    escape_next = False
    i = 0

    while i < len(json_str):
        char = json_str[i]

        if escape_next:
            result.append(char)
            escape_next = False
            i += 1
            continue

        if char == "\\" and in_string:
            escape_next = True
            result.append(char)
            i += 1
            continue

        if char == '"' and not escape_next:
            in_string = not in_string
            result.append(char)
            i += 1
            continue

        # Fix unescaped newlines inside strings
        if in_string and char == "\n":
            result.append("\\n")
            i += 1
            continue

        # Fix unescaped carriage returns inside strings
        if in_string and char == "\r":
            result.append("\\r")
            i += 1
            continue

        # Fix unescaped tabs inside strings
        if in_string and char == "\t":
            result.append("\\t")
            i += 1
            continue

        result.append(char)
        i += 1

    return "".join(result)


def find_json_object(text: str) -> str | None:
    """Find the first valid JSON object in text using balanced brace matching.

    This handles nested objects correctly, unlike simple regex like r'\\{[^{}]*\\}'.

    Args:
        text: The text to search for a JSON object.

    Returns:
        The first valid JSON object string found, or None if no valid JSON object exists.
    """
    start = text.find("{")
    if start == -1:
        return None

    depth = 0
    in_string = False
    escape_next = False

    for i, char in enumerate(text[start:], start):
        if escape_next:
            escape_next = False
            continue

        if char == "\\" and in_string:
            escape_next = True
            continue

        if char == '"' and not escape_next:
            in_string = not in_string
            continue

        if in_string:
            continue

        if char == "{":
            depth += 1
        elif char == "}":
            depth -= 1
            if depth == 0:
                return text[start : i + 1]

    return None


# Backwards compatibility alias
_fix_unescaped_newlines_in_json = fix_unescaped_newlines_in_json


__all__ = [
    "fix_unescaped_newlines_in_json",
    "find_json_object",
    "_fix_unescaped_newlines_in_json",
]
