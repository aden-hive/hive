"""Robust JSON extraction and processing for LLM-generated content."""

import json
import logging
import re
from typing import Any

logger = logging.getLogger(__name__)


def find_json_objects(text: str) -> list[str]:
    """Find all potential JSON objects in text using balanced brace matching.
    
    This is more robust than simple regex and handles nested objects.
    Returns a list of candidate JSON strings.
    """
    candidates = []
    
    # Fast path for markdown blocks
    markdown_blocks = re.findall(r"```(?:json)?\s*(.*?)```", text, re.DOTALL)
    for block in markdown_blocks:
        candidate = block.strip()
        if candidate.startswith("{") and candidate.endswith("}"):
            candidates.append(candidate)
            
    # Balanced brace matching for all occurrences
    start = 0
    while True:
        start = text.find("{", start)
        if start == -1:
            break
            
        depth = 0
        in_string = False
        escape_next = False
        
        for i in range(start, len(text)):
            char = text[i]
            
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
                    candidates.append(text[start : i + 1])
                    start = i  # Advance start to the end of this match
                    break
        
        start += 1  # Move past the first '{' to find next candidate
        
    # De-duplicate while preserving order
    seen = set()
    unique_candidates = []
    for c in candidates:
        if c not in seen:
            unique_candidates.append(c)
            seen.add(c)
            
    return unique_candidates


def _fix_unescaped_newlines_in_json(json_str: str) -> str:
    """Fix unescaped newlines inside JSON string values.
    
    LLMs sometimes output actual newlines inside JSON strings instead of \\n.
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

        # Fix unescaped newlines/tabs inside strings
        if in_string:
            if char == "\n":
                result.append("\\n")
                i += 1
                continue
            if char == "\r":
                result.append("\\r")
                i += 1
                continue
            if char == "\t":
                result.append("\\t")
                i += 1
                continue

        result.append(char)
        i += 1

    return "".join(result)


def extract_json(text: str, schema: dict | None = None) -> dict | None:
    """Extract and validate a JSON object from text.
    
    Args:
        text: Input text containing JSON.
        schema: Optional schema (TBD integration).
        
    Returns:
        The parsed dictionary, or None if extraction failed.
    """
    candidates = find_json_objects(text)
    
    for candidate in candidates:
        # Try raw
        try:
            return json.loads(candidate)
        except json.JSONDecodeError:
            pass
            
        # Try fixing unescaped newlines
        try:
            fixed = _fix_unescaped_newlines_in_json(candidate)
            return json.loads(fixed)
        except json.JSONDecodeError:
            pass
            
        # Try removing trailing commas (common LLM error)
        try:
            # Very simple regex for trailing commas in objects/arrays
            fixed = re.sub(r",\s*([}\]])", r"\1", candidate)
            return json.loads(fixed)
        except json.JSONDecodeError:
            pass
            
    return None
