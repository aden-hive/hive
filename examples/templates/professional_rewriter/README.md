Professional Rewriter

This template demonstrates a simple LLM-only Hive agent that rewrites informal text into more professional communication and returns structured outputs.

Input:
{"text":"yo vincent, im down to contribute. what should i do first?"}

Run:
uv run hive run examples/templates/professional_rewriter --input-file input.json --model anthropic/claude-sonnet-4-20250514

Expected outputs:
rewritten_text
tone
changes_made
final_check