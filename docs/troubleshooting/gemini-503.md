# Troubleshooting Gemini 503 (UNAVAILABLE / High Demand)

## Symptoms

When running an agent with Gemini (Vertex), execution may repeatedly retry and fail with an error similar to:

- `503 UNAVAILABLE`
- Message includes: "This model is currently experiencing high demand"

You may also see LiteLLM retry logs and messages like `MidStreamFallbackError`.

## Why this happens

This is a provider-side overload condition (temporary capacity or demand spike). Your environment can be correctly configured and still hit this error.

## Quick fixes

Try these in order:

1. **Retry later**
   - Spikes are often temporary.

2. **Switch models**
   - If using `gemini-3-flash-preview`, try `gemini-3.1-pro-preview` (often more stable during spikes).

3. **Reduce workload**
   - Shorten the request scope (example: “5 items from last 7 days”).
   - Ask for concise output.

4. **Avoid long streaming outputs**
   - If a setting exists to disable streaming, try turning it off.
   - Mid-stream failures can be more common under provider instability.

5. **Switch providers**
   - If you have keys available, try another provider temporarily (OpenAI, Anthropic, Groq, Cerebras).

## How to confirm it is not a local misconfiguration

If you can:
- launch the Hive UI successfully,
- run other lightweight prompts sometimes,
- and the logs specifically show `503 UNAVAILABLE` with “high demand”,

then this is almost certainly provider-side overload, not a local setup issue.

## Suggested resilience behavior (future improvement)

When transient 503 errors exceed retry thresholds, consider:
- configurable fallback model routing, or
- returning partial results with a clear “degraded” status.
