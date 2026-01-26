import json


def extract_json_object(text: str) -> dict:
    """
    Extract the first valid JSON object from an LLM response,
    including nested objects.

    Raises ValueError if no valid JSON is found.
    """
    start = text.find("{")
    if start == -1:
        raise ValueError("No JSON object found")

    brace_count = 0
    for i in range(start, len(text)):
        if text[i] == "{":
            brace_count += 1
        elif text[i] == "}":
            brace_count -= 1

            if brace_count == 0:
                candidate = text[start : i + 1]
                return json.loads(candidate)

    raise ValueError("Incomplete JSON object")
