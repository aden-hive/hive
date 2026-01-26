"""
LLM Metrics Demo
----------------
Demonstrates the observability features: token tracking, cost calculation,
latency monitoring, and performance analytics.

Run with:
    PYTHONPATH=core python core/examples/metrics_demo.py
"""

from framework.llm.litellm import LiteLLMProvider
from framework.observability.metrics import MetricsCollector

def main():
    print("🚀 Starting LLM Metrics Demo...\n")
    
    # Create metrics collector
    metrics = MetricsCollector()
    
    # Create LLM provider with metrics
    provider = LiteLLMProvider(
        model="gpt-4o-mini",
        metrics_collector=metrics
    )
    
    # Make a few test calls
    print("Making LLM calls...\n")
    
    # Call 1
    response1 = provider.complete(
        messages=[{"role": "user", "content": "Say hello"}]
    )
    print(f"✅ Call 1: {response1.content[:50]}...")
    
    # Call 2
    response2 = provider.complete(
        messages=[{"role": "user", "content": "What is 2+2?"}]
    )
    print(f"✅ Call 2: {response2.content[:50]}...")
    
    # Call 3
    response3 = provider.complete(
        messages=[{"role": "user", "content": "Tell me a joke"}]
    )
    print(f"✅ Call 3: {response3.content[:50]}...")
    
    # Display the beautiful dashboard
    metrics.print_dashboard()
    
    # Also get programmatic access
    summary = metrics.get_summary()
    print(f"\n📊 Programmatic Access:")
    print(f"Total Cost: ${summary['total_cost_usd']:.6f}")
    print(f"Total Tokens: {summary['total_tokens']:,}")
    print(f"Average Latency: {summary['avg_latency_ms']:.2f}ms")

if __name__ == "__main__":
    main()
