# StackOverflow Tool

Search StackOverflow questions and answers through the public StackExchange API.

## Available Tools

- `stackoverflow_search` - Search StackOverflow questions by query text and optional tags
- `stackoverflow_get_question` - Fetch a single question with its full HTML body and extracted code snippets
- `stackoverflow_get_question_answers` - Fetch answers for a question with bodies and extracted code snippets

## Authentication

No credentials are required for basic usage.

For higher rate limits, you may optionally set:

```bash
export STACKEXCHANGE_API_KEY="your_optional_key"
```

Without a key, StackExchange rate limits public usage per IP. The tool surfaces rate-limit errors when they occur.

## Usage

### Search questions

```python
stackoverflow_search(
    query="python requests timeout",
    tags=["python", "requests"],
    max_results=5,
)
```

### Fetch a question

```python
stackoverflow_get_question(question_id=123456)
```

### Fetch answers for a question

```python
stackoverflow_get_question_answers(
    question_id=123456,
    sort_by="votes",
    max_results=5,
)
```

## Response Shape

Question and answer responses include:

- raw `body` HTML from StackOverflow
- `body_text` with tags stripped for easier reading
- `code_snippets` extracted from `<pre><code>` blocks
- rate-limit metadata like `quota_remaining` and `backoff` when available

## API Reference

- StackExchange API docs: https://api.stackexchange.com/docs
- Advanced search: https://api.stackexchange.com/docs/advanced-search
- Questions by ID: https://api.stackexchange.com/docs/questions-by-ids
- Answers on questions: https://api.stackexchange.com/docs/answers-on-questions
