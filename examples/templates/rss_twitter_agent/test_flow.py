#!/usr/bin/env python
"""Focused tests for the RSS-to-Twitter interactive runner."""

from __future__ import annotations

import asyncio
import json

from .fetch import approve_threads
from . import agent as agent_module
from . import run as run_module
from . import twitter as twitter_module


def test_run_interactive_posts_approved_thread(monkeypatch) -> None:
    articles = [{"title": "A", "link": "https://example.com/a", "summary": "Sum"}]
    summaries = [
        {
            "title": "A",
            "url": "https://example.com/a",
            "hook": "Hook",
            "points": ["Point 1", "Point 2"],
            "why_it_matters": "Why",
            "hashtags": ["#Tech"],
        }
    ]
    post_calls: list[list[dict]] = []

    monkeypatch.setattr(run_module, "fetch_rss", lambda **_: json.dumps(articles))
    monkeypatch.setattr(
        run_module, "summarize_articles", lambda _: json.dumps(summaries)
    )
    monkeypatch.setattr(
        run_module,
        "_generate_thread_for_article",
        lambda summary: {
            "title": summary["title"],
            "tweets": ["tweet 1", "tweet 2", "tweet 3", "tweet 4"],
        },
    )

    async def fake_post(
        approved_json: str, twitter_credential_ref: str | None = None
    ) -> str:
        payload = json.loads(approved_json)
        post_calls.append(payload)
        return json.dumps({"success": True, "posted": len(payload[0]["tweets"])})

    monkeypatch.setattr(run_module, "post_to_twitter", fake_post)
    responses = iter(["y"])
    monkeypatch.setattr("builtins.input", lambda _prompt="": next(responses))

    result = asyncio.run(run_module.run_interactive(max_articles=1))

    assert result["success"] is True
    assert result["articles_fetched"] == 1
    assert result["threads_reviewed"] == 1
    assert result["threads_posted"] == 1
    assert len(post_calls) == 1


def test_run_interactive_quit_stops_remaining_threads(monkeypatch) -> None:
    articles = [
        {"title": "A", "link": "https://example.com/a", "summary": "Sum"},
        {"title": "B", "link": "https://example.com/b", "summary": "Sum"},
    ]
    summaries = [
        {
            "title": article["title"],
            "url": article["link"],
            "hook": article["title"],
            "points": ["Point 1"],
            "why_it_matters": "Why",
            "hashtags": ["#Tech"],
        }
        for article in articles
    ]
    post_calls: list[list[dict]] = []

    monkeypatch.setattr(run_module, "fetch_rss", lambda **_: json.dumps(articles))
    monkeypatch.setattr(
        run_module, "summarize_articles", lambda _: json.dumps(summaries)
    )
    monkeypatch.setattr(
        run_module,
        "_generate_thread_for_article",
        lambda summary: {
            "title": summary["title"],
            "tweets": ["tweet 1", "tweet 2", "tweet 3", "tweet 4"],
        },
    )

    async def fake_post(
        approved_json: str, twitter_credential_ref: str | None = None
    ) -> str:
        payload = json.loads(approved_json)
        post_calls.append(payload)
        return json.dumps({"success": True, "posted": len(payload[0]["tweets"])})

    monkeypatch.setattr(run_module, "post_to_twitter", fake_post)
    responses = iter(["q"])
    monkeypatch.setattr("builtins.input", lambda _prompt="": next(responses))

    result = asyncio.run(run_module.run_interactive(max_articles=2))

    assert result["threads_reviewed"] == 1
    assert result["threads_posted"] == 0
    assert post_calls == []


def test_approve_threads_keeps_prior_approvals_before_quit(monkeypatch) -> None:
    threads = [
        {"title": "A", "tweets": ["tweet 1"]},
        {"title": "B", "tweets": ["tweet 2"]},
    ]
    responses = iter(["y", "q"])
    monkeypatch.setattr("builtins.input", lambda _prompt="": next(responses))

    approved = json.loads(approve_threads(json.dumps(threads)))

    assert approved == [threads[0]]


def test_run_workflow_propagates_post_failure(monkeypatch) -> None:
    articles = [{"title": "A", "link": "https://example.com/a", "summary": "Sum"}]
    summaries = [
        {
            "title": "A",
            "url": "https://example.com/a",
            "hook": "Hook",
            "points": ["Point 1", "Point 2"],
            "why_it_matters": "Why",
            "hashtags": ["#Tech"],
        }
    ]

    monkeypatch.setattr(run_module, "fetch_rss", lambda **_: json.dumps(articles))
    monkeypatch.setattr(
        run_module, "summarize_articles", lambda _: json.dumps(summaries)
    )
    monkeypatch.setattr(
        run_module,
        "_generate_thread_for_article",
        lambda summary: {
            "title": summary["title"],
            "tweets": ["tweet 1", "tweet 2", "tweet 3", "tweet 4"],
        },
    )

    async def fake_post(
        approved_json: str, twitter_credential_ref: str | None = None
    ) -> str:
        return json.dumps({"success": False, "error": "session expired"})

    monkeypatch.setattr(run_module, "post_to_twitter", fake_post)
    monkeypatch.setattr("builtins.input", lambda _prompt="": "y")

    result = asyncio.run(run_module.run_workflow(max_articles=1))

    assert result["success"] is False
    assert result["threads_posted"] == 0
    assert "session expired" in result["error"]


def test_agent_preserves_explicit_zero_max_articles(monkeypatch) -> None:
    captured: dict[str, int | None] = {"max_articles": None}

    async def fake_workflow(
        feed_url: str = "https://news.ycombinator.com/rss",
        max_articles: int = 3,
        twitter_credential_ref: str | None = None,
    ) -> dict[str, object]:
        captured["max_articles"] = max_articles
        return {
            "success": True,
            "articles_json": "[]",
            "processed_json": "[]",
            "threads_json": "[]",
            "approved_json": "[]",
            "results_json": "[]",
        }

    monkeypatch.setattr(agent_module, "run_workflow", fake_workflow)

    result = asyncio.run(
        agent_module.default_agent.trigger_and_wait("start", {"max_articles": 0})
    )

    assert result.success is True
    assert captured["max_articles"] == 0


def test_post_threads_impl_reports_partial_failure(monkeypatch) -> None:
    async def fake_post_thread(
        thread: dict, credential_ref: str | None = None
    ) -> dict[str, object]:
        return {
            "title": thread["title"],
            "posted": 1,
            "total": 4,
            "error": "reply failed",
        }

    monkeypatch.setattr(
        twitter_module, "_post_thread_with_playwright", fake_post_thread
    )

    result = asyncio.run(
        twitter_module.post_threads_impl(
            json.dumps([{"title": "A", "tweets": ["1", "2", "3", "4"]}]),
            None,
            credential_ref="twitter/default",
        )
    )

    assert isinstance(result, dict)
    assert result["success"] is False
    assert "failed" in result["message"]
