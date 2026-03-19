# Stack Overflow Tool

Search Stack Overflow for coding questions and retrieve top answers. No API key required (10k requests/day on the public Stack Exchange API).

## Use Cases

- **Coding agents**: Look up solutions for errors, best practices, library usage
- **Support agents**: Find answers to technical questions
- **Research agents**: Gather community knowledge on a topic

## Tools

| Tool | Description |
|------|-------------|
| `stack_overflow_search` | Search questions by query, returns titles, excerpts, links, scores |
| `stack_overflow_get_answers` | Fetch top answers for a question by ID |

## Usage

```python
# Search for Python async timeout solutions
stack_overflow_search(query="python asyncio timeout", max_results=5)

# Get answers for a specific question (ID from search results)
stack_overflow_get_answers(question_id=12345678, max_answers=3)
```

## Arguments

### stack_overflow_search

| Arg | Type | Default | Description |
|-----|------|---------|-------------|
| query | str | required | Search term (e.g. "react useState") |
| site | str | "stackoverflow" | Stack Exchange site (serverfault, superuser, askubuntu) |
| max_results | int | 5 | Results to return (1-10) |
| sort | str | "relevance" | relevance, votes, creation, activity |

### stack_overflow_get_answers

| Arg | Type | Default | Description |
|-----|------|---------|-------------|
| question_id | int | required | Question ID from search results |
| site | str | "stackoverflow" | Stack Exchange site |
| max_answers | int | 3 | Answers to return (1-5) |

## Error Handling

Returns `{"error": "message"}` on failure. Common errors:
- Empty query
- API quota exceeded (10k/day without key)
- Question not found
- Network timeout
