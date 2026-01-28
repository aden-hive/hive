# LLM JSON Cleaner Tool

## Description

Returns a cleaned and schema-valid JSON object or array extracted from raw LLM output.

This tool is designed to handle common LLM issues such as conversational chatter, markdown fences, trailing commas, single quotes, incorrect types, missing required fields, and extra properties. It validates the extracted JSON against a provided JSON Schema and supports multiple correction modes.

Use this tool when working with LLMs that are expected to output structured JSON but may produce imperfect or non-compliant responses.

---

## Arguments

| Argument   | Type  | Required | Default | Description |
|------------|-------|----------|---------|-------------|
| llm_output | str   | Yes      | –       | Raw LLM response string containing JSON (may include chatter or markdown) |
| schema     | dict  | Yes      | –       | JSON Schema (draft-07 compatible) to validate against |
| mode       | str   | No       | `"coerce"` | Validation mode: `"strict"`, `"coerce"`, or `"force"` |

### Mode Behavior

- **strict**
  - No coercion or fixes
  - JSON must exactly match schema types and constraints

- **coerce**
  - Safe coercions only
  - Examples: `"42"` → `42`, `"true"` → `true`, trimming strings

- **force**
  - Aggressive schema compliance
  - Fills missing required fields
  - Removes extra properties
  - Clamps numeric constraints
  - Filters invalid array items
  - Records all forced fixes in metadata

---

## Returns

A dictionary with the following structure:

```json
{
  "data": { "...": "cleaned JSON data" } | null,
  "metadata": {
    "success": true | false,
    "errors": [
      {
        "stage": "extraction | syntax | schema",
        "path": "optional.json.path",
        "message": "error description"
      }
    ] | null,
    "forced_fixes": ["description of applied fix", ...] | null
  }
}
data is only the cleaned JSON (object or array)

All diagnostics are returned separately in metadata

Error Handling
Returns structured error objects for common failure cases:

No JSON found
stage: "extraction" — No {} or [] detected in LLM output

Unbalanced braces/brackets
stage: "extraction" — Incomplete JSON block

Invalid JSON syntax
stage: "syntax" — Trailing commas, quotes, or malformed JSON

Schema validation errors
stage: "schema" — Type mismatches, missing required fields, constraint violations

Errors include an optional JSON path when applicable.

Examples
Extract JSON from markdown and coerce types

llm_json_cleaner(
    '```json\n{"count": "42"}\n```',
    {
        "type": "object",
        "properties": {"count": {"type": "integer"}},
        "required": ["count"]
    },
    mode="coerce"
)
Result:

{
  "data": {"count": 42},
  "metadata": {"success": true}
}
