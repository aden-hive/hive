# Using Google Gemini

Google Gemini offers a free tier with 1500 requests per day, making it suitable for development, learning, and contributing to Hive.

## Why Gemini for Development

- **No Cost for Development** - 1500 requests per day with no credit card required
- **High Rate Limits** - 1 million tokens per minute
- **Fast Models** - Gemini 1.5 Flash is optimized for speed
- **Production Ready** - Same API works for paid tiers when scaling
- **Testing Flexibility** - Test agents without consuming paid API credits

## Get Your Free API Key

### Step 1: Visit Google AI Studio

Go to [https://aistudio.google.com/apikey](https://aistudio.google.com/apikey)

### Step 2: Sign In

Sign in with your Google account (Gmail, Workspace, etc.)

### Step 3: Create API Key

1. Click **"Get API Key"**
2. Select **"Create API Key"** (or use existing project)
3. Copy your API key

### Step 4: Set Environment Variable

Add to your shell profile (`~/.zshrc`, `~/.bashrc`, or `~/.bash_profile`):

```bash
export GOOGLE_API_KEY="your-api-key-here"
```

Then reload:
```bash
source ~/.zshrc  # or source ~/.bashrc
```

**Or** set it temporarily for a single session:
```bash
export GOOGLE_API_KEY="your-api-key-here"
PYTHONPATH=core:exports python -m your_agent run --input '{...}'
```

## Using Gemini in Agents

### Available Models

| Model | Best For | Speed | Capability |
|-------|----------|-------|------------|
| `gemini/gemini-1.5-flash` | Development, testing, fast responses | Fast | Good |
| `gemini/gemini-1.5-pro` | Complex tasks, production | Moderate | Excellent |
| `gemini/gemini-pro` | Legacy (use 1.5-flash instead) | Moderate | Good |

### Option 1: Using LiteLLMProvider (Recommended)

```python
from framework.llm import LiteLLMProvider

# Gemini 1.5 Flash - Fast model
provider = LiteLLMProvider(model="gemini/gemini-1.5-flash")

# Gemini 1.5 Pro - More capable
provider = LiteLLMProvider(model="gemini/gemini-1.5-pro")

# Generate completion
response = provider.complete(
    messages=[{"role": "user", "content": "Explain AI agents"}],
    system="You are a helpful AI assistant",
    max_tokens=1024
)

print(response.content)
```

### Option 2: In Agent Configuration

Update your agent's node configuration in `agent.json`:

```json
{
  "nodes": [
    {
      "node_id": "analyze",
      "name": "Analyze Input",
      "node_type": "llm_generate",
      "model": "gemini/gemini-1.5-flash",
      "system_prompt": "You are an expert analyst...",
      "input_keys": ["user_input"],
      "output_keys": ["analysis"]
    }
  ]
}
```

### Option 3: Environment Variable Override

Set the default model via environment variable:

```bash
export DEFAULT_LLM_MODEL="gemini/gemini-1.5-flash"
PYTHONPATH=core:exports python -m your_agent run --input '{...}'
```

## Free Tier Limits

### Daily Quotas (Free Tier)
- **Requests per day:** 1,500
- **Tokens per minute:** 1,000,000
- **Requests per minute:** 15

### What This Means for Development
- **Build & test agents** - Sufficient for daily development
- **Run comprehensive tests** - Adequate for most test suites
- **Iterate quickly** - Fast responses for rapid prototyping
- **Contribute to Hive** - Test contributions without cost

### If You Hit Limits
- Wait 24 hours for quota reset
- Switch to `gemini-1.5-flash` (faster, uses fewer resources)
- Use mock mode for testing: `--mock` flag
- Upgrade to paid tier for production workloads

## Example: Build a Calculator Agent

```bash
# 1. Set your API key
export GOOGLE_API_KEY="your-key-here"

# 2. Run the example calculator agent
cd /path/to/hive
PYTHONPATH=core python -m framework calculate "What is 25 * 4 + 10?"

# 3. Output
# Result: 110
```

## Troubleshooting

### Error: "API key not valid"
- Check your API key is correct
- Verify it's exported: `echo $GOOGLE_API_KEY`
- Try regenerating the key in AI Studio

### Error: "Quota exceeded"
- You've hit the daily limit (1500 requests)
- Wait 24 hours or upgrade to paid tier
- Use `--mock` mode for testing without API calls

### Error: "Module litellm not found"
- Install dependencies: `pip install litellm`
- Or run setup: `./scripts/setup-python.sh`

### Gemini returns empty responses
- Check your prompt isn't filtered by safety settings
- Try rephrasing your input
- Use Gemini 1.5 Pro for complex requests

## Upgrading to Paid Tier

When you're ready for production:

1. Go to [Google Cloud Console](https://console.cloud.google.com)
2. Enable billing on your project
3. **No code changes needed** - same API, same models!
4. Higher limits automatically apply

### Paid Tier Limits
- **Requests per day:** Unlimited
- **Tokens per minute:** 4,000,000+
- **Pay as you go:** ~$0.35 per 1M tokens (Flash)

## Best Practices

### For Development
```python
# Use Flash for speed during development
provider = LiteLLMProvider(model="gemini/gemini-1.5-flash")
```

### For Production
```python
# Use Pro for quality in production
provider = LiteLLMProvider(model="gemini/gemini-1.5-pro")
```

### Error Handling
```python
from framework.llm import LiteLLMProvider

try:
    provider = LiteLLMProvider(model="gemini/gemini-1.5-flash")
    response = provider.complete(messages=[...])
except Exception as e:
    print(f"Gemini API error: {e}")
    # Fallback to mock mode or different model
```

## Comparison with Other Providers

| Feature | Gemini (Free Tier) | Anthropic | OpenAI |
|---------|-------------------|-----------|--------|
| **Cost** | Free (limited) | $0.25-15/M tokens | $0.15-60/M tokens |
| **Free Tier** | 1500 req/day | No | No |
| **Setup Time** | < 1 minute | ~5 minutes | ~5 minutes |
| **Credit Card** | Not required | Required | Required |
| **Development Use** | Excellent | Good | Good |

## Additional Resources

- **Google AI Studio**: [https://aistudio.google.com](https://aistudio.google.com)
- **Gemini API Docs**: [https://ai.google.dev/docs](https://ai.google.dev/docs)
- **LiteLLM Gemini Guide**: [https://docs.litellm.ai/docs/providers/gemini](https://docs.litellm.ai/docs/providers/gemini)
- **Hive Discord**: [https://discord.com/invite/MXE49hrKDk](https://discord.com/invite/MXE49hrKDk)

---

With Gemini's free tier, you can build and test agents during development without API costs.
