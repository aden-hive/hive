"""Agent metadata + simple execution wrapper for RSS-to-Twitter Playwright flow."""

from __future__ import annotations

from framework.graph import Constraint, EdgeCondition, EdgeSpec, Goal, SuccessCriterion
from framework.graph.executor import ExecutionResult

from .config import metadata, validate_ollama
from .fetch import approve_threads, fetch_rss, generate_tweets, post_to_twitter, summarize_articles
from .nodes import approve_node, fetch_node, generate_node, post_node, process_node


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

    async def trigger_and_wait(self, entry_point: str, input_data: dict, timeout: float | None = None) -> ExecutionResult:
        feed_url = str(input_data.get("feed_url") or "https://news.ycombinator.com/rss")
        max_articles = int(input_data.get("max_articles") or 3)
        articles_json = fetch_rss(feed_url=feed_url, max_articles=max_articles)
        processed_json = summarize_articles(articles_json)
        threads_json = generate_tweets(processed_json)
        approved_json = approve_threads(threads_json)
        results_json = await post_to_twitter(approved_json)

        return ExecutionResult(
            success=True,
            output={
                "articles_json": articles_json,
                "processed_json": processed_json,
                "threads_json": threads_json,
                "approved_json": approved_json,
                "results_json": results_json,
            },
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
