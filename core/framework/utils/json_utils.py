"""
JSON utility functions for the framework.
"""

import json
import logging
import re
import os
from typing import Any

logger = logging.getLogger(__name__)


def find_json_object(text: str) -> str | None:
    """Find the first valid JSON object in text using balanced brace matching.

    This handles nested objects correctly, unlike simple regex like r'\\{[^{}]*\\}'.
    """
    start = text.find('{')
    if start == -1:
        return None

    depth = 0
    in_string = False
    escape_next = False

    for i, char in enumerate(text[start:], start):
        if escape_next:
            escape_next = False
            continue

        if char == '\\' and in_string:
            escape_next = True
            continue

        if char == '"' and not escape_next:
            in_string = not in_string
            continue

        if in_string:
            continue

        if char == '{':
            depth += 1
        elif char == '}':
            depth -= 1
            if depth == 0:
                return text[start:i + 1]

    return None


def extract_json(raw_response: str, output_keys: list[str]) -> dict[str, Any]:
    """Extract clean JSON from potentially verbose LLM response.

    Tries multiple extraction strategies in order:
    1. Direct JSON parse
    2. Markdown code block extraction
    3. Balanced brace matching
    4. Haiku LLM fallback (last resort)
    """
    content = raw_response.strip()

    # Try direct JSON parse first (fast path)
    try:
        # Use strip_code_blocks to handle markdown wrappers
        clean_content = strip_code_blocks(content)
        parsed = json.loads(clean_content)
        if isinstance(parsed, dict):
            return parsed
    except json.JSONDecodeError:
        pass

    # Start fresh with content in case first strip didn't work (though it should have)
    # The original code had retry logic with different regexes, but strip_code_blocks covers most.
    # Let's keep the explicit regex check just in case, or just rely on strip_code_blocks?
    # Original logic:
    # 1. strip markdown (if present) -> parse
    # 2. regex match markdown -> parse
    # 3. find_json_object -> parse

    # Since strip_code_blocks covers 1 and 2, we can simplify.

    # Try to find JSON object by matching balanced braces (use module-level helper)
    json_str = find_json_object(content)
    if json_str:
        try:
            parsed = json.loads(json_str)
            if isinstance(parsed, dict):
                return parsed
        except json.JSONDecodeError:
            pass

    # All local extraction methods failed - use LLM as last resort
    # Prefer Cerebras (faster/cheaper), fallback to Anthropic Haiku
    api_key = os.environ.get("CEREBRAS_API_KEY") or os.environ.get("ANTHROPIC_API_KEY")
    if not api_key:
        raise ValueError("Cannot parse JSON and no API key for LLM cleanup (set CEREBRAS_API_KEY or ANTHROPIC_API_KEY)")

    # Use fast LLM to clean the response (Cerebras llama-3.3-70b preferred)
    from framework.llm.litellm import LiteLLMProvider
    if os.environ.get("CEREBRAS_API_KEY"):
        cleaner_llm = LiteLLMProvider(
            api_key=os.environ.get("CEREBRAS_API_KEY"),
            model="cerebras/llama-3.3-70b",
            temperature=0.0
        )
    else:
        # Fallback to Anthropic Haiku
        from framework.llm.anthropic import AnthropicProvider
        cleaner_llm = AnthropicProvider(model="claude-3-5-haiku-20241022")

    prompt = f"""Extract the JSON object from this LLM response.

Expected output keys: {output_keys}

LLM Response:
{raw_response}

Output ONLY the JSON object, nothing else."""

    try:
        result = cleaner_llm.complete(
            messages=[{"role": "user", "content": prompt}],
            system="Extract JSON from text. Output only valid JSON.",
            json_mode=True,
        )

        cleaned = result.content.strip()
        cleaned = strip_code_blocks(cleaned)

        parsed = json.loads(cleaned)
        logger.info("      ✓ LLM cleaned JSON output")
        return parsed

    except ValueError:
        raise  # Re-raise our descriptive error
    except Exception as e:
        logger.warning(f"      ⚠ LLM JSON extraction failed: {e}")
        raise


def strip_code_blocks(content: str) -> str:
    """Strip markdown code block wrappers from content.

    removes ```json...``` wrappers to get clean content.
    """
    content = content.strip()
    # Match ```json or ``` at start and ``` at end (greedy to handle nested)
    match = re.match(r'^```(?:json|JSON)?\s*\n?(.*)\n?```\s*$', content, re.DOTALL)
    if match:
        return match.group(1).strip()
        
    # Fallback: strip first/last lines if they look like code fences
    lines = content.split('\n')
    if len(lines) >= 2 and lines[0].startswith('```') and lines[-1].strip() == '```':
        return '\n'.join(lines[1:-1]).strip()
        
    return content
