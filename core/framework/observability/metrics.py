"""Metrics collection for LLM operations"""
from dataclasses import dataclass
from datetime import datetime

@dataclass
class LLMCallMetrics:
    timestamp: datetime
    node_id: str
    model: str
    input_tokens: int
    output_tokens: int
    latency_ms: float
    cost_usd: float
    success: bool
    error: str | None = None

class MetricsCollector:
    def __init__(self):
        self.calls = []
        self.total_cost = 0.0
        self.total_tokens = 0
        
    PRICING = {
        "gpt-4o": {"input": 2.50, "output": 10.00},
        "gpt-4o-mini": {"input": 0.15, "output": 0.60},
        "claude-3-5-sonnet-20241022": {"input": 3.00, "output": 15.00},
        "claude-3-5-haiku-20241022": {"input": 0.80, "output": 4.00},
        "gemini-2.0-flash": {"input": 0.075, "output": 0.30},
        "gemini-1.5-pro": {"input": 1.25, "output": 5.00},
    }
        
    def calculate_cost(self, model: str, input_tokens: int, output_tokens: int) -> float:
        rates = self.PRICING.get(model, {"input": 1.0, "output": 2.0})
        input_cost = (input_tokens / 1_000_000) * rates["input"]
        output_cost = (output_tokens / 1_000_000) * rates["output"]
        return input_cost + output_cost
    
    def record_call(self, node_id: str, model: str, input_tokens: int, 
                   output_tokens: int, latency_ms: float, success: bool = True, error: str | None = None):
        cost = self.calculate_cost(model, input_tokens, output_tokens) if success else 0.0
        
        metric = LLMCallMetrics(
            timestamp=datetime.now(),
            node_id=node_id,
            model=model,
            input_tokens=input_tokens,
            output_tokens=output_tokens,
            latency_ms=latency_ms,
            cost_usd=cost,
            success=success,
            error=error
        )
        
        self.calls.append(metric)
        if success:
            self.total_cost += cost
            self.total_tokens += input_tokens + output_tokens
        
    def get_summary(self):
        total_calls = len(self.calls)
        successful_calls = sum(1 for c in self.calls if c.success)
        failed_calls = total_calls - successful_calls
        
        # Calculate latency stats
        latencies = [c.latency_ms for c in self.calls]
        avg_latency = sum(latencies) / max(len(latencies), 1)
        min_latency = min(latencies) if latencies else 0
        max_latency = max(latencies) if latencies else 0
        
        # Cost breakdown by model
        cost_by_model = {}
        tokens_by_model = {}
        for call in self.calls:
            if call.success:
                cost_by_model[call.model] = cost_by_model.get(call.model, 0) + call.cost_usd
                tokens_by_model[call.model] = tokens_by_model.get(call.model, 0) + call.input_tokens + call.output_tokens
        
        # Find most expensive call
        most_expensive = max(self.calls, key=lambda c: c.cost_usd) if self.calls else None
        slowest_call = max(self.calls, key=lambda c: c.latency_ms) if self.calls else None
        
        return {
            "total_calls": total_calls,
            "successful_calls": successful_calls,
            "failed_calls": failed_calls,
            "total_tokens": self.total_tokens,
            "total_cost_usd": round(self.total_cost, 6),
            "success_rate": round(successful_calls / max(total_calls, 1), 4),
            "avg_latency_ms": round(avg_latency, 2),
            "min_latency_ms": round(min_latency, 2),
            "max_latency_ms": round(max_latency, 2),
            "cost_by_model": {k: round(v, 6) for k, v in cost_by_model.items()},
            "tokens_by_model": tokens_by_model,
            "most_expensive_call": {
                "model": most_expensive.model,
                "cost_usd": round(most_expensive.cost_usd, 6),
                "tokens": most_expensive.input_tokens + most_expensive.output_tokens
            } if most_expensive else None,
            "slowest_call": {
                "model": slowest_call.model,
                "latency_ms": round(slowest_call.latency_ms, 2),
                "node_id": slowest_call.node_id
            } if slowest_call else None,
        }
    
    def print_dashboard(self):
        """Print a beautiful monitoring dashboard"""
        summary = self.get_summary()
        
        print("\n" + "="*60)
        print("📊 LLM OBSERVABILITY DASHBOARD")
        print("="*60)
        
        print("\n💰 COST ANALYSIS:")
        print(f"   Total Cost: ${summary['total_cost_usd']:.6f}")
        if summary['cost_by_model']:
            print("   Cost by Model:")
            for model, cost in summary['cost_by_model'].items():
                print(f"      • {model}: ${cost:.6f}")
        
        print("\n🎯 TOKEN USAGE:")
        print(f"   Total Tokens: {summary['total_tokens']:,}")
        if summary['tokens_by_model']:
            print("   Tokens by Model:")
            for model, tokens in summary['tokens_by_model'].items():
                print(f"      • {model}: {tokens:,}")
        
        print("\n⏱️  PERFORMANCE METRICS:")
        print(f"   Average Latency: {summary['avg_latency_ms']:.2f}ms")
        print(f"   Min Latency: {summary['min_latency_ms']:.2f}ms")
        print(f"   Max Latency: {summary['max_latency_ms']:.2f}ms")
        
        print("\n📈 CALL STATISTICS:")
        print(f"   Total Calls: {summary['total_calls']}")
        print(f"   Successful: {summary['successful_calls']}")
        print(f"   Failed: {summary['failed_calls']}")
        print(f"   Success Rate: {summary['success_rate']*100:.1f}%")
        
        if summary['most_expensive_call']:
            print("\n💸 MOST EXPENSIVE CALL:")
            mec = summary['most_expensive_call']
            print(f"   Model: {mec['model']}")
            print(f"   Cost: ${mec['cost_usd']:.6f}")
            print(f"   Tokens: {mec['tokens']:,}")
        
        if summary['slowest_call']:
            print("\n🐌 SLOWEST CALL:")
            sc = summary['slowest_call']
            print(f"   Node: {sc['node_id']}")
            print(f"   Model: {sc['model']}")
            print(f"   Latency: {sc['latency_ms']:.2f}ms")
        
        print("\n" + "="*60 + "\n")
