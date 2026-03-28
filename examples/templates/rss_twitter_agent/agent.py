"""Agent metadata + simple execution wrapper for RSS-to-Twitter Playwright flow."""

from __future__ import annotations

import asyncio

from framework.graph import Constraint, EdgeCondition, EdgeSpec, Goal, SuccessCriterion
from framework.graph.executor import ExecutionResult

from .config import metadata, validate_ollama
from .nodes import approve_node, fetch_node, generate_node, post_node, process_node
from .run import run_workflow


goal = Goal(
    id="rss-to-twitter",
    name="RSS-to-Twitter Content Repurposing",
    description=(
        "Fetch articles from RSS feeds, summarize them, generate engaging Twitter threads, "
        "ask for explicit user approval, and post approved threads via Playwright."
    ),
    success_criteria=[
        SuccessCriterion(
            id="feed-parsing",
            description="Agent fetches and parses at least one feed item",
            metric="article_count",
            target=">=1",
            weight=0.3,
        ),
        SuccessCriterion(
            id="thread-quality",
            description="Generated threads contain structured tweets with CTA and link",
            metric="thread_count",
            target=">=1",
            weight=0.35,
        ),
        SuccessCriterion(
            id="approval-gate",
            description="User explicitly approves/rejects each thread",
            metric="approval_present",
            target="true",
            weight=0.2,
        ),
        SuccessCriterion(
            id="posting",
            description="Approved threads are posted through Playwright",
            metric="post_success",
            target="true when approved",
            weight=0.15,
        ),
    ],
    constraints=[
        Constraint(
            id="human-approval-required",
            description="Posting requires explicit human y/n decision",
            constraint_type="safety",
            category="approval",
        ),
        Constraint(
            id="source-attribution",
            description="Threads should include source links",
            constraint_type="quality",
            category="content",
        ),
    ],
)

nodes = [fetch_node, process_node, generate_node, approve_node, post_node]
edges = [
    EdgeSpec(
        id="fetch-to-process",
        source="fetch",
        target="process",
        condition=EdgeCondition.ON_SUCCESS,
        priority=1,
    ),
    EdgeSpec(
        id="process-to-generate",
        source="process",
        target="generate",
        condition=EdgeCondition.ON_SUCCESS,
        priority=1,
    ),
    EdgeSpec(
        id="generate-to-approve",
        source="generate",
        target="approve",
        condition=EdgeCondition.ON_SUCCESS,
        priority=1,
    ),
    EdgeSpec(
        id="approve-to-post",
        source="approve",
        target="post",
        condition=EdgeCondition.ON_SUCCESS,
        priority=1,
    ),
]

entry_node = "fetch"
entry_points = {"start": "fetch"}
terminal_nodes = ["post"]


class RSSTwitterAgent:
    """Lightweight wrapper preserving the original interactive Playwright workflow."""

    def __init__(self):
        self.goal = goal
        self.nodes = nodes
        self.edges = edges
        self.entry_node = entry_node
        self.entry_points = entry_points
        self.terminal_nodes = terminal_nodes

    async def start(self) -> None:
        ok, msg = validate_ollama()
        if not ok:
            raise RuntimeError(msg)

    async def stop(self) -> None:
        return None

    async def trigger_and_wait(
        self, entry_point: str, input_data: dict, timeout: float | None = None
    ) -> ExecutionResult:
        feed_url = str(input_data.get("feed_url") or "https://news.ycombinator.com/rss")
        raw_max_articles = input_data.get("max_articles")
        max_articles = 3 if raw_max_articles in (None, "") else int(raw_max_articles)
        twitter_credential_ref = input_data.get("twitter_credential_ref")
        workflow_coro = run_workflow(
            feed_url=feed_url,
            max_articles=max_articles,
            twitter_credential_ref=(
                str(twitter_credential_ref) if twitter_credential_ref else None
            ),
        )
        try:
            workflow = (
                await asyncio.wait_for(workflow_coro, timeout=timeout)
                if timeout is not None
                else await workflow_coro
            )
        except asyncio.TimeoutError:
            return ExecutionResult(
                success=False,
                error=f"RSS-to-Twitter workflow timed out after {timeout} seconds.",
                steps_executed=0,
            )

        return ExecutionResult(
            success=bool(workflow.get("success", True)),
            output={
                "articles_json": workflow.get("articles_json", "[]"),
                "processed_json": workflow.get("processed_json", "[]"),
                "threads_json": workflow.get("threads_json", "[]"),
                "approved_json": workflow.get("approved_json", "[]"),
                "results_json": workflow.get("results_json", "[]"),
            },
            error=workflow.get("error"),
            steps_executed=5,
        )

    async def run(self, context: dict) -> ExecutionResult:
        await self.start()
        try:
            return await self.trigger_and_wait("start", context)
        finally:
            await self.stop()

    def info(self) -> dict:
        return {
            "name": metadata.name,
            "version": metadata.version,
            "description": metadata.description,
            "goal": {"name": self.goal.name, "description": self.goal.description},
            "nodes": [n.id for n in self.nodes],
            "entry_node": self.entry_node,
            "terminal_nodes": self.terminal_nodes,
        }

    def validate(self) -> dict:
        errors: list[str] = []
        node_ids = {n.id for n in self.nodes}
        if self.entry_node not in node_ids:
            errors.append(f"Entry node '{self.entry_node}' not found")
        for edge in self.edges:
            if edge.source not in node_ids:
                errors.append(f"Edge {edge.id}: source '{edge.source}' not found")
            if edge.target not in node_ids:
                errors.append(f"Edge {edge.id}: target '{edge.target}' not found")
        return {"valid": not errors, "errors": errors, "warnings": []}


default_agent = RSSTwitterAgent()
