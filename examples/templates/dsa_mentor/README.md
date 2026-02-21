# Template: DSA Mentor Agent

An AI coding mentor that helps developers learn Data Structures and Algorithms through guided hints, code review, weakness identification, and personalized practice plans.

## Overview

The DSA Mentor Agent acts as a personalized tutor for algorithm learning. Unlike coding platforms that just provide problems, this agent:

- **Provides progressive hints** without revealing complete solutions
- **Reviews code** for correctness, complexity, and optimization opportunities
- **Identifies weak areas** (e.g., dynamic programming, graphs, greedy algorithms)
- **Suggests targeted practice** problems based on identified weaknesses

## Workflow

```
[intake] → [analyze-problem] → [provide-hint]
                                    ↓
                            [review-code] (if code provided)
                                    ↓
                            [identify-weaknesses]
                                    ↓
                            [suggest-practice]
```

### Flow Details

1. **Intake** (client-facing): Collects problem statement, user code (optional), questions, and difficulty level
2. **Analyze Problem**: Classifies problem by topic, difficulty, key concepts, and common pitfalls
3. **Provide Hint** (client-facing): Generates progressive hints (4 levels) without revealing solutions
4. **Review Code** (conditional): Reviews code if provided - checks correctness, complexity, suggests optimizations
5. **Identify Weaknesses**: Analyzes patterns to identify weak DSA areas
6. **Suggest Practice** (client-facing): Creates personalized practice plan with 3-5 problems per weak area

## Nodes

| Node | Type | Client-Facing | Description |
|------|------|---------------|-------------|
| `intake` | `event_loop` | ✅ Yes | Collects problem statement, user code, questions |
| `analyze-problem` | `event_loop` | ❌ No | Classifies problem by topic, difficulty, concepts |
| `provide-hint` | `event_loop` | ✅ Yes | Generates progressive hints (never reveals solutions) |
| `review-code` | `event_loop` | ❌ No | Reviews code for correctness, complexity, optimization |
| `identify-weaknesses` | `event_loop` | ❌ No | Identifies weak DSA areas from code review |
| `suggest-practice` | `event_loop` | ✅ Yes | Creates personalized practice plan |

## Key Features

### Progressive Hint System

The hint system has 4 levels of specificity:
- **Level 1 (Vague)**: General approach direction
- **Level 2 (Moderate)**: More specific guidance
- **Level 3 (Specific)**: Algorithm pattern hints
- **Level 4 (Detailed)**: Detailed step-by-step guidance

**Critical**: The agent NEVER provides complete solutions, only hints and guidance.

### Code Review

When users provide code, the agent reviews:
- Correctness (bugs, edge cases)
- Time complexity (Big O analysis)
- Space complexity
- Optimization opportunities
- Code quality and style

### Weakness Identification

Tracks patterns across problems to identify:
- Weak topics (DP, graphs, greedy, etc.)
- Strength areas
- Recurring mistakes
- Learning gaps

### Personalized Practice Plans

Creates targeted practice recommendations:
- 3-5 problems per weak area
- Difficulty progression (easy → medium → hard)
- Problem descriptions and relevance
- Key concepts to practice

## Usage

### Basic Execution

```bash
# Run with default input
python3 -m examples.templates.dsa_mentor

# Run with custom input
python3 -m examples.templates.dsa_mentor --input '{
  "problem_statement": "Find two numbers in array that sum to target",
  "user_code": "def two_sum(nums, target): ...",
  "user_question": "Is my approach optimal?",
  "difficulty_level": "medium"
}'
```

### Interactive TUI Mode

For full interactive experience:

```bash
# Launch TUI dashboard
python3 -m examples.templates.dsa_mentor tui
```

**Note**: TUI mode requires:
- `textual` package installed: `python3 -m pip install textual`
- `ANTHROPIC_API_KEY` environment variable set

### Structure Validation

```bash
# Quick structure test (no API calls)
python3 -c "
from examples.templates.dsa_mentor import DSAMentorAgent
agent = DSAMentorAgent()
graph = agent._build_graph()
print(f'Graph: {len(graph.nodes)} nodes, {len(graph.edges)} edges')
"
```

## Input Schema

```json
{
  "problem_statement": "string (required)",
  "user_code": "string (optional)",
  "user_question": "string (optional)",
  "difficulty_level": "string (optional: easy/medium/hard)"
}
```

## Output Schema

```json
{
  "hint": "string",
  "code_review": {
    "correctness": "correct/incorrect/partial",
    "time_complexity": "O(...)",
    "space_complexity": "O(...)",
    "is_optimal": boolean,
    "optimization_suggestions": ["..."],
    "positive_feedback": "...",
    "improvements_needed": ["..."]
  },
  "weak_areas": [
    {
      "topic": "string",
      "severity": "high/medium/low",
      "evidence": "string"
    }
  ],
  "practice_plan": [
    {
      "weak_area": "string",
      "problems": [
        {
          "name": "string",
          "description": "string",
          "difficulty": "easy/medium/hard",
          "why_relevant": "string",
          "key_concepts": ["string"]
        }
      ]
    }
  ]
}
```

## Escalation Logic

The agent handles various scenarios:

| Trigger | Action |
|---------|--------|
| User asks for full solution | Provides structured hints instead |
| Incorrect solution after multiple attempts | Provides guided walkthrough |
| Repeated weakness in one topic | Recommends focused learning plan |
| Advanced optimization questions | Provides multi-step hints |

## Constraints

### Hard Constraints

- **No Direct Solutions**: Never provide complete solutions or working code
- **Educational Focus**: Always guide learning, not just solve problems

### Soft Constraints

- **Progressive Hints**: Start vague, get more specific if needed
- **Encouraging Tone**: Provide constructive, positive feedback
- **Actionable Feedback**: Make suggestions specific and implementable

## Customization Ideas

- **LeetCode Integration**: Add tool to fetch problems from LeetCode API
- **Progress Tracking**: Store learning history in local database or Notion
- **GitHub Gists**: Save solutions and feedback as gists
- **Slack/Discord**: Daily practice reminders
- **Codeforces Integration**: Fetch problems from Codeforces
- **Video Tutorials**: Link to relevant video explanations

## File Structure

```
dsa_mentor/
├── __init__.py          # Package exports
├── __main__.py          # CLI entry point with TUI support
├── agent.py             # Goal, edges, graph spec, DSAMentorAgent class
├── config.py            # RuntimeConfig and AgentMetadata
├── nodes/
│   └── __init__.py      # All 6 NodeSpec definitions
└── README.md            # This file
```

## Example Interactions

### Scenario 1: Hint Request

**User**: "I'm stuck on the two sum problem. Can you help?"

**Agent Flow**:
1. Intake collects problem statement
2. Analyzes: "Arrays, hash map pattern, O(n) solution possible"
3. Provides Level 1 hint: "Think about using a data structure that allows O(1) lookups"
4. If user needs more: Escalates to Level 2-4 hints
5. Identifies weakness: "Arrays and hash maps"
6. Suggests practice: "Try 'Contains Duplicate', 'Group Anagrams'"

### Scenario 2: Code Review

**User**: "Here's my code for binary tree traversal. Is it correct?"

**Agent Flow**:
1. Intake collects code
2. Analyzes problem
3. Reviews code: "Correct but O(n) space. Can you do it in O(1)?"
4. Identifies weakness: "Tree traversal, space optimization"
5. Suggests practice: "Try iterative solutions, Morris traversal"

## Testing

The agent structure can be validated without API calls:

```bash
# Test graph structure
python3 -c "
from examples.templates.dsa_mentor import DSAMentorAgent
agent = DSAMentorAgent()
graph = agent._build_graph()
assert len(graph.nodes) == 6
assert len(graph.edges) == 7
assert graph.entry_node == 'intake'
assert 'suggest-practice' in graph.terminal_nodes
print('✅ All tests passed!')
"
```

## Requirements

- Python 3.11+
- Framework dependencies (installed via `./quickstart.sh`)
- `textual` package for TUI mode (optional): `python3 -m pip install textual`
- `ANTHROPIC_API_KEY` for LLM calls (or other provider key)

## Related

- [Implementation Plan](../../../ISSUE_4927_IMPLEMENTATION_PLAN.md)
- [Full Checklist](../../../ISSUE_4927_CHECKLIST.md)
- [Hive Framework Documentation](../../../../docs/getting-started.md)

## License

Apache 2.0 - See [LICENSE](../../../../LICENSE)
