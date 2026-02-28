# RSS-to-Twitter Agent (Playwright)

This template keeps the original behavior:

1. Fetch RSS news
2. Summarize with Ollama
3. Ask you `y/n/q` per thread
4. If `y`, auto-open Twitter/X and post via Playwright

Updated for Hive v0.6+ project layout and credential namespace support.

## Run

From repo root:

```bash
cd /Users/vasu/Desktop/hive
export PYTHONPATH=core:examples/templates

python -m rss_twitter_agent run \
  --feed-url "https://news.ycombinator.com/rss" \
  --max-articles 3
```

Optional credential ref (v0.6 format):

```bash
python -m rss_twitter_agent run \
  --feed-url "https://news.ycombinator.com/rss" \
  --max-articles 3 \
  --twitter-credential-ref twitter/default
```

## Validate / Info

```bash
python -m rss_twitter_agent validate
python -m rss_twitter_agent info
```

## Ollama prerequisites

```bash
ollama serve
ollama pull llama3.2
```

## Behavior notes

- First posting run opens browser login and stores session.
- Later runs reuse session automatically.
- You can override session path with `HIVE_TWITTER_SESSION_DIR`.
- Credential reference uses `{name}/{alias}` (example: `twitter/default`).
