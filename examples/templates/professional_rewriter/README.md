# Professional Rewriter Agent

A simple LLM-only agent template that rewrites informal or casual text into polished, professional communication.

## What It Does

1. **Intake** — Receives the informal text and optional context (audience, purpose)
2. **Rewrite** — Transforms the text into professional language
3. **Deliver** — Presents the result with structured outputs and invites adjustments

## Outputs

| Field | Description |
|---|---|
| `rewritten_text` | The polished, professional version of the input |
| `tone` | The identified tone (e.g., "formal business", "warm professional") |
| `changes_made` | Summary of changes applied (slang removed, restructured, etc.) |
| `final_check` | Quality confirmation that the original intent is preserved |

## Usage

```bash
hive run examples/templates/professional_rewriter --input '{"text": "hey wanted to ask if u can review my pr asap its kinda urgent lol"}'
```

## Example

**Input:**
```
hey wanted to ask if u can review my pr asap its kinda urgent lol
```

**Output:**
```
rewritten_text: I wanted to kindly request your review of my pull request at your earliest
convenience. This is a time-sensitive matter that requires prompt attention.

tone: warm professional

changes_made: Removed slang ("hey", "u", "lol"), added formal greeting, replaced
"asap" with "at your earliest convenience", added appropriate context about urgency.

final_check: The rewrite preserves the original request and urgency while using
professional language suitable for workplace communication.
```

## No Tools Required

This agent runs on LLM calls only — no external tools or API credentials needed.
