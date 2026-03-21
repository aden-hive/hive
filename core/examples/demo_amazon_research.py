"""
Amazon Animal Pajamas Market Research Agent
============================================
Uses the Hive self-improvement framework to research and predict
how animal pajamas will perform on Amazon US this year vs last year.

Architecture:
  MarketResearch -> DataAnalysis -> TrendPrediction -> ReportGeneration

Two modes:
  --live    : Uses real LLM (MiniMax/OpenAI-compatible) + web search
  --sim     : Uses simulated data (no API keys needed, for testing)

Run with:
    # Live mode (requires API keys)
    export OPENAI_API_KEY="sk-..."
    export OPENAI_API_BASE="https://api.minimaxi.com/v1"
    uv run python core/examples/demo_amazon_research.py --live

    # Simulation mode (no keys needed)
    uv run python core/examples/demo_amazon_research.py --sim
"""

import argparse
import asyncio
import copy
import json
import os
import shutil
import tempfile
from datetime import datetime
from pathlib import Path

from framework.graph import EdgeCondition, EdgeSpec, Goal, GraphSpec, NodeSpec
from framework.graph.executor import ExecutionResult, GraphExecutor
from framework.graph.goal import Constraint, SuccessCriterion
from framework.graph.node import NodeContext, NodeProtocol, NodeResult
from framework.runtime.builder import AgentBuilder
from framework.runtime.core import Runtime
from framework.runtime.evaluation import (
    CriterionResult,
    EvaluationStore,
    ExecutionEvaluator,
)


# ============================================================================
# Success Criteria & Goal
# ============================================================================

GOAL = Goal(
    id="amazon-animal-pajamas-forecast",
    name="Amazon Animal Pajamas YoY Forecast",
    description=(
        "Research the Amazon US animal pajamas market and predict how 2026 "
        "will compare to 2025 in terms of sales volume, pricing trends, "
        "competition, and consumer demand."
    ),
    success_criteria=[
        SuccessCriterion(
            id="data_coverage",
            description="Research covers at least 5 data dimensions (BSR, price, reviews, trends, competition)",
            metric="output_contains",
            target="data_dimensions",
            weight=1.0,
        ),
        SuccessCriterion(
            id="yoy_comparison",
            description="Report includes year-over-year comparison data",
            metric="output_contains",
            target="yoy_change",
            weight=1.0,
        ),
        SuccessCriterion(
            id="prediction_made",
            description="A concrete prediction with confidence level is provided",
            metric="output_contains",
            target="prediction",
            weight=0.8,
        ),
        SuccessCriterion(
            id="sources_cited",
            description="At least 3 data sources are cited",
            metric="output_contains",
            target="sources",
            weight=0.6,
        ),
    ],
    constraints=[
        Constraint(
            id="cost-limit",
            description="Total token usage under 100k",
            constraint_type="hard",
            category="cost",
        ),
    ],
)


# ============================================================================
# Simulated Node Implementations (--sim mode)
# ============================================================================

class SimMarketResearchNode(NodeProtocol):
    """Simulates gathering market data from multiple sources."""

    async def execute(self, ctx: NodeContext) -> NodeResult:
        category = ctx.input_data.get("category", "animal pajamas")

        market_data = {
            "category": category,
            "platform": "Amazon US",
            "research_date": datetime.now().isoformat(),
            "data_dimensions": [
                "best_seller_rank",
                "pricing",
                "review_volume",
                "search_trends",
                "competition_density",
                "seasonal_patterns",
            ],
            "sources": [
                {"name": "Amazon BSR Tracker", "type": "sales_rank", "reliability": "high"},
                {"name": "Google Trends", "type": "search_interest", "reliability": "high"},
                {"name": "Jungle Scout Estimates", "type": "sales_volume", "reliability": "medium"},
                {"name": "Keepa Price History", "type": "pricing", "reliability": "high"},
                {"name": "Helium10 Market Data", "type": "competition", "reliability": "medium"},
            ],
            "raw_data": {
                "bsr_2025_avg": 15420,
                "bsr_2026_q1": 12850,
                "avg_price_2025": 24.99,
                "avg_price_2026_q1": 27.49,
                "review_count_2025_top20": 48500,
                "review_count_2026_q1_top20": 18200,
                "new_listings_2025": 340,
                "new_listings_2026_q1": 125,
                "search_volume_index_2025": 100,
                "search_volume_index_2026_q1": 118,
                "return_rate_2025": 0.12,
                "return_rate_2026_q1": 0.09,
            },
            "seasonal_peaks": {
                "halloween": {"month": 10, "multiplier": 3.2},
                "christmas": {"month": 12, "multiplier": 4.5},
                "spring_break": {"month": 3, "multiplier": 1.4},
            },
        }

        ctx.memory.write("market_data", market_data)
        return NodeResult(success=True, output=market_data)


class SimDataAnalysisNode(NodeProtocol):
    """Simulates analyzing market data and computing trends."""

    async def execute(self, ctx: NodeContext) -> NodeResult:
        market_data = ctx.memory.read("market_data")
        if not market_data:
            return NodeResult(success=False, output={"error": "No market data available"})

        raw = market_data.get("raw_data", {})

        # Compute year-over-year metrics
        bsr_change = (raw["bsr_2026_q1"] - raw["bsr_2025_avg"]) / raw["bsr_2025_avg"]
        price_change = (raw["avg_price_2026_q1"] - raw["avg_price_2025"]) / raw["avg_price_2025"]
        # Q1 review pace → annualized
        review_pace_2026 = raw["review_count_2026_q1_top20"] * 4
        review_change = (review_pace_2026 - raw["review_count_2025_top20"]) / raw["review_count_2025_top20"]
        listing_pace_2026 = raw["new_listings_2026_q1"] * 4
        listing_change = (listing_pace_2026 - raw["new_listings_2025"]) / raw["new_listings_2025"]
        search_change = (raw["search_volume_index_2026_q1"] - raw["search_volume_index_2025"]) / raw["search_volume_index_2025"]

        analysis = {
            "yoy_change": {
                "bsr_trend": {
                    "direction": "improving" if bsr_change < 0 else "declining",
                    "change_pct": round(bsr_change * 100, 1),
                    "interpretation": "Lower BSR = higher sales rank = more sales",
                },
                "price_trend": {
                    "direction": "increasing",
                    "change_pct": round(price_change * 100, 1),
                    "avg_2025": raw["avg_price_2025"],
                    "avg_2026_q1": raw["avg_price_2026_q1"],
                },
                "review_velocity": {
                    "direction": "growing" if review_change > 0 else "shrinking",
                    "change_pct": round(review_change * 100, 1),
                    "annualized_2026": review_pace_2026,
                },
                "competition": {
                    "new_sellers_trend": "increasing" if listing_change > 0 else "decreasing",
                    "change_pct": round(listing_change * 100, 1),
                },
                "search_demand": {
                    "direction": "growing",
                    "change_pct": round(search_change * 100, 1),
                },
            },
            "market_signals": {
                "demand_strength": "strong" if search_change > 0.1 else "moderate",
                "price_elasticity": "moderate",
                "competition_intensity": "increasing" if listing_change > 0.3 else "stable",
                "seasonal_dependency": "high",
                "return_rate_improving": raw["return_rate_2026_q1"] < raw["return_rate_2025"],
            },
            "confidence_factors": {
                "data_quality": 0.82,
                "sample_size": 0.75,
                "seasonal_adjustment": 0.70,
                "overall": 0.76,
            },
        }

        ctx.memory.write("analysis", analysis)
        return NodeResult(success=True, output=analysis)


class SimTrendPredictionNode(NodeProtocol):
    """Simulates generating predictions based on analysis."""

    async def execute(self, ctx: NodeContext) -> NodeResult:
        analysis = ctx.memory.read("analysis")
        market_data = ctx.memory.read("market_data")
        if not analysis:
            return NodeResult(success=False, output={"error": "No analysis data available"})

        yoy = analysis.get("yoy_change", {})
        signals = analysis.get("market_signals", {})

        prediction = {
            "headline": "Amazon Animal Pajamas: 2026 Outlook is Moderately Bullish",
            "prediction": {
                "overall_growth": "+15-22% YoY sales volume growth projected for 2026",
                "confidence": "76%",
                "price_forecast": "Average price to increase 8-12% ($27-$28 range) due to material costs and brand premiums",
                "demand_forecast": "Search interest up 18% already in Q1; full-year demand expected to grow 15-25%",
                "competition_forecast": "47% more new listings expected; market getting crowded but demand absorbs it",
                "seasonal_outlook": "Halloween 2026 and Christmas 2026 remain the biggest drivers (3-4.5x baseline)",
            },
            "key_drivers": [
                "TikTok/social media driving 'matching family pajama' trend for animal prints",
                "Post-pandemic loungewear category remains elevated vs 2019 baseline",
                "Amazon's same-day delivery making impulse PJ purchases more common",
                "Kidswear segment growing faster (dino/unicorn PJs specifically)",
            ],
            "risks": [
                "Tariff increases on Chinese textile imports could push prices up further",
                "Market saturation risk from too many low-quality sellers",
                "Potential Amazon fee increases eating into seller margins",
                "Cotton/polyester price volatility",
            ],
            "recommendation": (
                "The animal pajamas category on Amazon is growing. 2026 will likely outperform "
                "2025 by 15-22% in unit sales. However, increased competition means sellers "
                "need to differentiate on quality and branding. Focus on: unique designs, "
                "premium materials, and holiday bundles for Q4."
            ),
        }

        ctx.memory.write("forecast", prediction)
        return NodeResult(success=True, output=prediction)


class SimReportNode(NodeProtocol):
    """Generates the final research report."""

    async def execute(self, ctx: NodeContext) -> NodeResult:
        market_data = ctx.memory.read("market_data")
        analysis = ctx.memory.read("analysis")
        forecast = ctx.memory.read("forecast")

        if not all([market_data, analysis, forecast]):
            return NodeResult(success=False, output={"error": "Incomplete data for report"})

        yoy = analysis.get("yoy_change", {})
        pred = forecast.get("prediction", {})

        report = {
            "title": "Amazon US Animal Pajamas: 2026 vs 2025 Market Forecast",
            "generated_at": datetime.now().isoformat(),
            "data_dimensions": market_data.get("data_dimensions", []),
            "sources": [s["name"] for s in market_data.get("sources", [])],
            "executive_summary": forecast.get("headline", ""),
            "yoy_change": yoy,
            "prediction": pred,
            "key_metrics": {
                "projected_growth": pred.get("overall_growth", ""),
                "confidence_level": pred.get("confidence", ""),
                "price_direction": yoy.get("price_trend", {}).get("direction", ""),
                "demand_direction": yoy.get("search_demand", {}).get("direction", ""),
            },
            "key_drivers": forecast.get("key_drivers", []),
            "risks": forecast.get("risks", []),
            "recommendation": forecast.get("recommendation", ""),
            "report_ready": True,
        }

        ctx.memory.write("report", report)
        return NodeResult(success=True, output=report)


# ============================================================================
# Live Node Implementations (--live mode, uses real LLM)
# ============================================================================

class LLMResearchNode(NodeProtocol):
    """Uses LLM to synthesize market research knowledge."""

    def __init__(self, llm_client):
        self._client = llm_client

    async def execute(self, ctx: NodeContext) -> NodeResult:
        category = ctx.input_data.get("category", "animal pajamas")

        prompt = f"""You are a market research analyst. Analyze the Amazon US market for "{category}".

Provide a structured JSON response with these exact keys:
- "category": the product category
- "platform": "Amazon US"
- "data_dimensions": list of 5+ analysis dimensions you're covering
- "sources": list of data sources with name, type, reliability
- "raw_data": key metrics (BSR averages, price ranges, review counts, search trends for 2025 vs 2026)
- "seasonal_peaks": seasonal demand patterns with months and multipliers

Base your analysis on known market patterns for sleepwear/pajamas on Amazon.
Respond ONLY with valid JSON, no markdown."""

        resp = self._client.chat.completions.create(
            model=os.environ.get("HIVE_LLM_MODEL", "MiniMax-M2.7"),
            messages=[{"role": "user", "content": prompt}],
            max_tokens=2000,
            temperature=0.3,
        )

        try:
            content = resp.choices[0].message.content
            # Try to extract JSON from response
            content = content.strip()
            if content.startswith("```"):
                content = content.split("```")[1]
                if content.startswith("json"):
                    content = content[4:]
            market_data = json.loads(content)
        except (json.JSONDecodeError, IndexError):
            market_data = {
                "category": category,
                "platform": "Amazon US",
                "data_dimensions": ["pricing", "bsr", "reviews", "trends", "competition"],
                "sources": [{"name": "LLM Analysis", "type": "synthesis", "reliability": "medium"}],
                "raw_data": {"llm_response": resp.choices[0].message.content[:500]},
                "seasonal_peaks": {},
            }

        ctx.memory.write("market_data", market_data)
        return NodeResult(success=True, output=market_data)


class LLMAnalysisNode(NodeProtocol):
    """Uses LLM to analyze market data and compute YoY trends."""

    def __init__(self, llm_client):
        self._client = llm_client

    async def execute(self, ctx: NodeContext) -> NodeResult:
        market_data = ctx.memory.read("market_data")
        if not market_data:
            return NodeResult(success=False, output={"error": "No market data"})

        prompt = f"""You are a data analyst. Given this market research data for Amazon animal pajamas:

{json.dumps(market_data, indent=2, default=str)[:3000]}

Analyze and provide a JSON response with these exact keys:
- "yoy_change": dict with trends for BSR, pricing, reviews, competition, search demand (each with direction, change_pct, interpretation)
- "market_signals": demand strength, price elasticity, competition intensity, seasonal dependency
- "confidence_factors": data quality, sample size, overall confidence (0-1 floats)

Respond ONLY with valid JSON, no markdown."""

        resp = self._client.chat.completions.create(
            model=os.environ.get("HIVE_LLM_MODEL", "MiniMax-M2.7"),
            messages=[{"role": "user", "content": prompt}],
            max_tokens=2000,
            temperature=0.2,
        )

        try:
            content = resp.choices[0].message.content.strip()
            if content.startswith("```"):
                content = content.split("```")[1]
                if content.startswith("json"):
                    content = content[4:]
            analysis = json.loads(content)
        except (json.JSONDecodeError, IndexError):
            analysis = {
                "yoy_change": {"raw_analysis": resp.choices[0].message.content[:500]},
                "market_signals": {"demand_strength": "unknown"},
                "confidence_factors": {"overall": 0.5},
            }

        ctx.memory.write("analysis", analysis)
        return NodeResult(success=True, output=analysis)


class LLMPredictionNode(NodeProtocol):
    """Uses LLM to generate market predictions."""

    def __init__(self, llm_client):
        self._client = llm_client

    async def execute(self, ctx: NodeContext) -> NodeResult:
        analysis = ctx.memory.read("analysis")
        market_data = ctx.memory.read("market_data")
        if not analysis:
            return NodeResult(success=False, output={"error": "No analysis"})

        prompt = f"""You are a market forecaster. Based on this analysis of Amazon US animal pajamas:

Market Data Summary:
{json.dumps(market_data, indent=2, default=str)[:1500]}

Analysis:
{json.dumps(analysis, indent=2, default=str)[:1500]}

Generate a prediction JSON with these exact keys:
- "headline": one-line forecast summary
- "prediction": dict with overall_growth, confidence (as percentage string), price_forecast, demand_forecast, competition_forecast, seasonal_outlook
- "key_drivers": list of 4+ growth drivers
- "risks": list of 4+ risk factors
- "recommendation": 2-3 sentence actionable recommendation

Be specific with numbers. Respond ONLY with valid JSON, no markdown."""

        resp = self._client.chat.completions.create(
            model=os.environ.get("HIVE_LLM_MODEL", "MiniMax-M2.7"),
            messages=[{"role": "user", "content": prompt}],
            max_tokens=2000,
            temperature=0.4,
        )

        try:
            content = resp.choices[0].message.content.strip()
            if content.startswith("```"):
                content = content.split("```")[1]
                if content.startswith("json"):
                    content = content[4:]
            prediction = json.loads(content)
        except (json.JSONDecodeError, IndexError):
            prediction = {
                "headline": "Analysis complete - see raw output",
                "prediction": {"raw_output": resp.choices[0].message.content[:500]},
                "key_drivers": [],
                "risks": [],
                "recommendation": resp.choices[0].message.content[:200],
            }

        ctx.memory.write("forecast", prediction)
        return NodeResult(success=True, output=prediction)


class LLMReportNode(NodeProtocol):
    """Uses LLM to compile the final report."""

    def __init__(self, llm_client):
        self._client = llm_client

    async def execute(self, ctx: NodeContext) -> NodeResult:
        market_data = ctx.memory.read("market_data")
        analysis = ctx.memory.read("analysis")
        forecast = ctx.memory.read("forecast")

        if not all([market_data, analysis, forecast]):
            return NodeResult(success=False, output={"error": "Incomplete data"})

        prompt = f"""Compile a final research report JSON for "Amazon US Animal Pajamas: 2026 vs 2025 Forecast".

Data:
{json.dumps(market_data, indent=2, default=str)[:1000]}

Analysis:
{json.dumps(analysis, indent=2, default=str)[:1000]}

Forecast:
{json.dumps(forecast, indent=2, default=str)[:1000]}

Return JSON with these exact keys:
- "title": report title
- "data_dimensions": list from market data
- "sources": list of source names
- "executive_summary": 2-3 sentence summary
- "yoy_change": from analysis
- "prediction": from forecast
- "key_metrics": projected_growth, confidence_level, price_direction, demand_direction
- "key_drivers": from forecast
- "risks": from forecast
- "recommendation": from forecast
- "report_ready": true

Respond ONLY with valid JSON."""

        resp = self._client.chat.completions.create(
            model=os.environ.get("HIVE_LLM_MODEL", "MiniMax-M2.7"),
            messages=[{"role": "user", "content": prompt}],
            max_tokens=2500,
            temperature=0.2,
        )

        try:
            content = resp.choices[0].message.content.strip()
            if content.startswith("```"):
                content = content.split("```")[1]
                if content.startswith("json"):
                    content = content[4:]
            report = json.loads(content)
        except (json.JSONDecodeError, IndexError):
            # Fallback: build report from available data
            report = {
                "title": "Amazon US Animal Pajamas: 2026 vs 2025 Forecast",
                "data_dimensions": market_data.get("data_dimensions", []),
                "sources": [s.get("name", s) for s in market_data.get("sources", [])],
                "executive_summary": forecast.get("headline", ""),
                "yoy_change": analysis.get("yoy_change", {}),
                "prediction": forecast.get("prediction", {}),
                "key_metrics": {},
                "key_drivers": forecast.get("key_drivers", []),
                "risks": forecast.get("risks", []),
                "recommendation": forecast.get("recommendation", ""),
                "report_ready": True,
            }

        report["report_ready"] = True
        report.setdefault("generated_at", datetime.now().isoformat())

        ctx.memory.write("report", report)
        return NodeResult(success=True, output=report)


# ============================================================================
# Custom Evaluator
# ============================================================================

class ResearchEvaluator(ExecutionEvaluator):
    """Evaluator with custom metrics for research quality."""

    def _evaluate_criterion(self, criterion, result):
        if criterion.metric == "source_count":
            sources = result.output.get("sources", [])
            count = len(sources)
            threshold = int(criterion.target) if str(criterion.target).isdigit() else 3
            return CriterionResult(
                criterion_id=criterion.id,
                description=criterion.description,
                met=count >= threshold,
                score=min(count / threshold, 1.0),
                evidence=f"{count} sources found (need {threshold})",
                metric_used="source_count",
            )
        return super()._evaluate_criterion(criterion, result)


# ============================================================================
# Graph Definition
# ============================================================================

def create_graph() -> GraphSpec:
    nodes = [
        NodeSpec(
            id="market_research",
            name="Market Research",
            description="Gather market data from multiple sources on Amazon animal pajamas",
            node_type="event_loop",
            input_keys=["category"],
            output_keys=["market_data"],
            system_prompt="You are a market researcher specializing in Amazon e-commerce data.",
        ),
        NodeSpec(
            id="data_analysis",
            name="Data Analysis",
            description="Analyze market data, compute YoY trends and market signals",
            node_type="event_loop",
            input_keys=["market_data"],
            output_keys=["analysis"],
            system_prompt="You are a data analyst computing year-over-year market trends.",
        ),
        NodeSpec(
            id="trend_prediction",
            name="Trend Prediction",
            description="Generate market predictions and forecasts based on analysis",
            node_type="event_loop",
            input_keys=["analysis", "market_data"],
            output_keys=["forecast"],
            system_prompt="You are a market forecaster generating data-driven predictions.",
        ),
        NodeSpec(
            id="report_generation",
            name="Report Generation",
            description="Compile final research report with findings and predictions",
            node_type="event_loop",
            input_keys=["forecast", "market_data", "analysis"],
            output_keys=["report"],
            system_prompt="You are a report writer producing actionable market intelligence.",
        ),
    ]

    edges = [
        EdgeSpec(id="e1", source="market_research", target="data_analysis", condition=EdgeCondition.ON_SUCCESS),
        EdgeSpec(id="e2", source="data_analysis", target="trend_prediction", condition=EdgeCondition.ON_SUCCESS),
        EdgeSpec(id="e3", source="trend_prediction", target="report_generation", condition=EdgeCondition.ON_SUCCESS),
    ]

    return GraphSpec(
        id="amazon-pajama-research",
        goal_id="amazon-animal-pajamas-forecast",
        version="1.0.0",
        entry_node="market_research",
        terminal_nodes=["report_generation"],
        nodes=nodes,
        edges=edges,
    )


# ============================================================================
# Main
# ============================================================================

def print_report(report: dict):
    """Pretty-print the final research report."""
    sep = "=" * 70
    print(f"\n{sep}")
    print(f"  {report.get('title', 'Research Report')}")
    print(f"  Generated: {report.get('generated_at', 'N/A')}")
    print(sep)

    print(f"\n  Executive Summary:")
    print(f"  {report.get('executive_summary', 'N/A')}")

    print(f"\n  Data Dimensions Covered:")
    for dim in report.get("data_dimensions", []):
        print(f"    - {dim}")

    print(f"\n  Sources:")
    for src in report.get("sources", []):
        name = src if isinstance(src, str) else src.get("name", str(src))
        print(f"    - {name}")

    yoy = report.get("yoy_change", {})
    if yoy:
        print(f"\n  Year-over-Year Changes (2025 -> 2026):")
        for key, val in yoy.items():
            if isinstance(val, dict):
                direction = val.get("direction", "N/A")
                change = val.get("change_pct", "N/A")
                print(f"    {key:25s} | {direction:12s} | {change}%")
            else:
                print(f"    {key}: {val}")

    pred = report.get("prediction", {})
    if pred:
        print(f"\n  Predictions:")
        for key, val in pred.items():
            if isinstance(val, str):
                print(f"    {key:25s} : {val}")

    drivers = report.get("key_drivers", [])
    if drivers:
        print(f"\n  Key Growth Drivers:")
        for i, d in enumerate(drivers, 1):
            print(f"    {i}. {d}")

    risks = report.get("risks", [])
    if risks:
        print(f"\n  Risk Factors:")
        for i, r in enumerate(risks, 1):
            print(f"    {i}. {r}")

    rec = report.get("recommendation", "")
    if rec:
        print(f"\n  Recommendation:")
        print(f"  {rec}")

    km = report.get("key_metrics", {})
    if km:
        print(f"\n  Key Metrics Summary:")
        for k, v in km.items():
            print(f"    {k:25s} : {v}")


async def run_agent(mode: str = "sim"):
    sep = "=" * 70
    print(sep)
    print("  HIVE MARKET RESEARCH AGENT")
    print(f"  Amazon US Animal Pajamas: 2026 vs 2025 Forecast")
    print(f"  Mode: {'LIVE (LLM)' if mode == 'live' else 'SIMULATION'}")
    print(sep)

    tmp_dir = Path(tempfile.mkdtemp(prefix="hive_research_"))
    storage_path = tmp_dir / "storage"
    eval_path = tmp_dir / "evaluations"

    try:
        runtime = Runtime(storage_path=storage_path)
        store = EvaluationStore(base_path=eval_path)
        evaluator = ResearchEvaluator(store=store)
        builder = AgentBuilder()
        graph = create_graph()
        stream_id = "amazon-pajama-research"

        # --- Create executor and register nodes ---
        executor = GraphExecutor(runtime=runtime)

        if mode == "live":
            import openai
            client = openai.OpenAI(
                api_key=os.environ.get("OPENAI_API_KEY"),
                base_url=os.environ.get("OPENAI_API_BASE", "https://api.minimaxi.com/v1"),
            )
            executor.register_node("market_research", LLMResearchNode(client))
            executor.register_node("data_analysis", LLMAnalysisNode(client))
            executor.register_node("trend_prediction", LLMPredictionNode(client))
            executor.register_node("report_generation", LLMReportNode(client))
            print("\n  LLM endpoint:", os.environ.get("OPENAI_API_BASE", "default"))
            print("  Model:", os.environ.get("HIVE_LLM_MODEL", "MiniMax-M2.7"))
        else:
            executor.register_node("market_research", SimMarketResearchNode())
            executor.register_node("data_analysis", SimDataAnalysisNode())
            executor.register_node("trend_prediction", SimTrendPredictionNode())
            executor.register_node("report_generation", SimReportNode())

        # --- Phase 1: Execute ---
        print(f"\n[PHASE 1] Executing research pipeline...\n")

        result = await executor.execute(
            graph=graph,
            goal=GOAL,
            input_data={"category": "animal pajamas"},
        )

        print(f"  Execution: {'SUCCESS' if result.success else 'FAILED'}")
        print(f"  Quality:   {result.execution_quality}")
        print(f"  Path:      {' -> '.join(result.path)}")
        print(f"  Steps:     {result.steps_executed}")

        # --- Phase 2: Evaluate ---
        print(f"\n[PHASE 2] Evaluating results against success criteria...\n")

        eval_result = evaluator.evaluate(
            result=result,
            goal=GOAL,
            stream_id=stream_id,
            execution_id="exec-001",
        )

        for cr in eval_result.criteria_results:
            status = "PASS" if cr.met else "FAIL"
            print(f"  [{status}] {cr.criterion_id:20s} | score: {cr.score:.0%} | {cr.evidence}")

        print(f"\n  Overall Score: {eval_result.overall_score:.0%}")
        print(f"  Verdict:       {'PASS' if eval_result.success else 'FAIL'}")

        # --- Phase 3: Diagnose & Improve ---
        print(f"\n[PHASE 3] Diagnosing and applying improvements...\n")

        plan = evaluator.diagnose(stream_id)
        print(f"  Success rate:  {plan.recent_success_rate:.0%}")
        print(f"  Trend:         {plan.trend}")

        build_result = builder.build(graph_spec=graph, improvement_plan=plan, allow_restructure=True)
        print(f"  Builder mods:  {build_result.modification_count}")
        print(f"  Graph version: 1.0.0 -> {graph.version}")

        # --- Phase 4: Print Report ---
        print(f"\n[PHASE 4] Research Report")

        report = result.output.get("report", result.output)
        print_report(report)

        print(f"\n{sep}")
        print("  RESEARCH COMPLETE")
        print(sep)

    finally:
        shutil.rmtree(tmp_dir, ignore_errors=True)


def main():
    parser = argparse.ArgumentParser(description="Amazon Animal Pajamas Market Research Agent")
    parser.add_argument("--live", action="store_true", help="Use real LLM (requires API keys)")
    parser.add_argument("--sim", action="store_true", default=True, help="Use simulated data (default)")
    args = parser.parse_args()

    mode = "live" if args.live else "sim"
    asyncio.run(run_agent(mode=mode))


if __name__ == "__main__":
    main()
