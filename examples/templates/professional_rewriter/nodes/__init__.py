"""Node definitions for Professional Rewriter."""

from framework.graph import NodeSpec

# Node 1: Rewrite (autonomous entry node)
# The queen handles intake and passes text via run_agent_with_input({"text": "..."})
rewrite_node = NodeSpec(
    id="rewrite",
    name="Professional Rewriter",
    description="Rewrite text professionally with tone analysis and change tracking",
    node_type="event_loop",
    max_node_visits=0,  # Unlimited for forever-alive
    input_keys=["text"],
    output_keys=["rewritten_text", "tone", "changes_made", "final_check"],
    success_criteria="Text is rewritten professionally with valid JSON output.",
    system_prompt="""\
You are a professional text rewriter. Your task is to rewrite the provided text to improve clarity, professionalism, and readability while preserving the original meaning.

The text to rewrite is in memory under "text".

Work in phases:
1. **Analyze the original text**: Identify tone, style, and key points
2. **Rewrite professionally**: Improve clarity, grammar, structure, and flow
3. **Track changes**: Note specific improvements made
4. **Validate output**: Ensure the rewrite maintains original meaning

Call set_output in a SEPARATE turn with these exact keys:
- set_output("rewritten_text", "the professionally rewritten version")
- set_output("tone", "description of the tone used (e.g., 'formal business', 'academic', 'conversational professional')")  
- set_output("changes_made", "JSON array of specific changes as strings")
- set_output("final_check", "true if rewrite maintains original meaning and is professional, false otherwise")

Requirements:
- rewritten_text must be non-empty
- tone should be a concise description
- changes_made must be a valid JSON array of strings describing improvements
- final_check must be "true" or "false" as a string
""",
    tools=[],
)

# Node 2: Validate (validation step)
validate_node = NodeSpec(
    id="validate",
    name="Output Validator",
    description="Validate that output is valid JSON and meets requirements",
    node_type="event_loop",
    max_node_visits=0,
    input_keys=["rewritten_text", "tone", "changes_made", "final_check"],
    output_keys=["validation_result", "final_output"],
    success_criteria="Output is validated as proper JSON with non-empty rewritten_text.",
    system_prompt="""\
You are a validation specialist. Your task is to validate the rewriting output and format it as valid JSON.

Check the following requirements:
1. rewritten_text must be non-empty
2. tone should be a meaningful description
3. changes_made must be parseable as a JSON array
4. final_check should be "true" or "false"

If all validations pass, create the final JSON output. If any fail, set validation_result to describe the issue.

Call set_output in a SEPARATE turn:
- set_output("validation_result", "valid" if all checks pass, otherwise describe the issue)
- set_output("final_output", "complete JSON object as string" if valid, otherwise "null")

Final JSON format:
{
  "rewritten_text": "...",
  "tone": "...",
  "changes_made": [...],
  "final_check": true/false
}
""",
    tools=[],
)

__all__ = ["rewrite_node", "validate_node"]