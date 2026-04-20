"""RSS fetch + LLM summarization + approval + post helpers."""

from __future__ import annotations

import ipaddress
import json
import os
import socket
import xml.etree.ElementTree as ET
from urllib.parse import urljoin, urlparse

import httpx

from .config import get_ollama_model, get_ollama_url


def _is_public_ip(host: str) -> bool:
    """Reject loopback/private/link-local targets to avoid local network fetches."""
    try:
        address = ipaddress.ip_address(host)
    except ValueError:
        return False
    return not (
        address.is_private
        or address.is_loopback
        or address.is_link_local
        or address.is_multicast
        or address.is_reserved
        or address.is_unspecified
    )


def _validate_public_feed_url(feed_url: str) -> str:
    """Allow only http(s) URLs that resolve to public destinations."""
    parsed = urlparse(feed_url)
    if parsed.scheme not in {"http", "https"} or not parsed.hostname:
        raise ValueError("Feed URL must use http(s) and include a hostname.")

    try:
        addrinfo = socket.getaddrinfo(
            parsed.hostname, parsed.port or None, proto=socket.IPPROTO_TCP
        )
    except OSError as exc:
        raise ValueError(f"Could not resolve feed host '{parsed.hostname}'.") from exc

    if not addrinfo:
        raise ValueError(f"Could not resolve feed host '{parsed.hostname}'.")

    for family, *_rest, sockaddr in addrinfo:
        host = sockaddr[0] if family in (socket.AF_INET, socket.AF_INET6) else None
        if not host or not _is_public_ip(host):
            raise ValueError("Feed URL must resolve to a public network destination.")

    return feed_url


def _fetch_public_feed(feed_url: str, max_redirects: int = 5) -> str:
    """Fetch RSS while validating every redirect target against SSRF-prone destinations."""
    current_url = _validate_public_feed_url(feed_url)
    with httpx.Client(follow_redirects=False) as client:
        for _ in range(max_redirects + 1):
            resp = client.get(current_url, timeout=10.0)
            if resp.status_code in {301, 302, 303, 307, 308}:
                location = resp.headers.get("location")
                if not location:
                    break
                current_url = _validate_public_feed_url(
                    urljoin(str(resp.url), location)
                )
                continue
            resp.raise_for_status()
            return resp.text
    raise ValueError("Too many redirects while fetching feed URL.")


def _valid_summary_item(item: object) -> bool:
    return (
        isinstance(item, dict)
        and isinstance(item.get("title"), str)
        and isinstance(item.get("url"), str)
        and isinstance(item.get("hook"), str)
        and isinstance(item.get("why_it_matters"), str)
        and isinstance(item.get("points"), list)
        and all(isinstance(point, str) for point in item["points"])
        and isinstance(item.get("hashtags"), list)
        and all(isinstance(tag, str) for tag in item["hashtags"])
    )


def _valid_thread_payload(item: object) -> bool:
    return (
        isinstance(item, dict)
        and isinstance(item.get("title"), str)
        and isinstance(item.get("tweets"), list)
        and len(item["tweets"]) >= 3
        and all(isinstance(tweet, str) and tweet.strip() for tweet in item["tweets"])
    )


def fetch_rss(
    feed_url: str = "https://news.ycombinator.com/rss", max_articles: int = 3
) -> str:
    """Fetch RSS feed and return parsed articles as JSON string."""
    try:
        xml_content = _fetch_public_feed(feed_url)
    except Exception:
        return json.dumps([])

    try:
        root = ET.fromstring(xml_content)
    except ET.ParseError:
        return json.dumps([])

    articles = []
    for item in root.findall(".//item")[:max_articles]:
        title_elem = item.find("title")
        link_elem = item.find("link")
        desc_elem = item.find("description")

        article = {
            "title": title_elem.text if title_elem is not None else "",
            "link": link_elem.text if link_elem is not None else "",
            "summary": (
                desc_elem.text[:150] if desc_elem is not None and desc_elem.text else ""
            ),
            "source": "Hacker News",
        }
        articles.append(article)

    return json.dumps(articles)


def _call_ollama(prompt: str, max_tokens: int = 800) -> str:
    """Call Ollama API directly via HTTP."""
    model = get_ollama_model()
    try:
        with httpx.Client() as client:
            resp = client.post(
                f"{get_ollama_url()}/api/generate",
                json={
                    "model": model,
                    "prompt": prompt,
                    "stream": False,
                    "options": {"num_predict": max_tokens, "temperature": 0.75},
                },
                timeout=90.0,
            )
            resp.raise_for_status()
            data = resp.json()
            return data.get("response", "[]")
    except Exception as e:
        print(f"Ollama error: {e}")
        return "[]"


def summarize_articles(articles_json: str) -> str:
    """Summarize articles into rich tweet-ready format using Ollama."""
    articles = json.loads(articles_json) if articles_json else []
    if not articles:
        return json.dumps([])

    prompt = f"""You are a tech journalist. For each article below, extract rich context for Twitter threads.
Return ONLY a JSON array — one object per article — with this exact format:
[
  {{
    "title": "article title",
    "url": "article url",
    "hook": "one punchy sentence that grabs attention — a surprising fact, bold claim, or question",
    "points": ["key insight 1", "key insight 2", "key insight 3"],
    "why_it_matters": "one sentence on why this is important or interesting",
    "hashtags": ["#Tag1", "#Tag2", "#Tag3"]
  }}
]

Articles:
{json.dumps(articles, indent=2)}

Return ONLY the JSON array, no other text:"""

    text = _call_ollama(prompt, 900)

    start = text.find("[")
    end = text.rfind("]") + 1
    if start >= 0 and end > start:
        try:
            parsed = json.loads(text[start:end])
            if (
                isinstance(parsed, list)
                and parsed
                and all(_valid_summary_item(item) for item in parsed)
            ):
                return json.dumps(parsed)
        except json.JSONDecodeError:
            pass

    return json.dumps(
        [
            {
                "title": a["title"],
                "url": a["link"],
                "hook": a["title"],
                "points": [a.get("summary", "")[:150]],
                "why_it_matters": "",
                "hashtags": ["#Tech"],
            }
            for a in articles
        ]
    )


def _generate_thread_for_article(summary: dict) -> dict | None:
    """Generate one high-quality Twitter thread for a single article."""
    title = summary.get("title", "News")
    url = summary.get("url", "")
    hook = summary.get("hook", title)
    points = summary.get("points", [])
    why = summary.get("why_it_matters", "")
    hashtags = " ".join(summary.get("hashtags", ["#Tech"])[:3])
    title_literal = json.dumps(title[:60])

    prompt = f"""You are a viral tech Twitter personality. Write an engaging 4-tweet thread about this article.

Article: {title}
URL: {url}
Hook: {hook}
Key points: {json.dumps(points)}
Why it matters: {why}
Hashtags to use: {hashtags}

Rules:
- Tweet 1: Start with 🧵 and a PUNCHY hook — a bold claim, surprising fact, or provocative question. Max 240 chars.
- Tweet 2: Start with \"1/\" — explain the core idea in plain English. Conversational, not corporate. Max 260 chars.
- Tweet 3: Start with \"2/\" — give the most interesting insight or implication. Use an emoji. Max 260 chars.
- Tweet 4: Start with \"3/\" — why this matters + call to action + the URL + hashtags. Max 280 chars.
- Sound like a real person, not a press release.

Return ONLY a JSON object with this exact structure (no other text):
{{"title": {title_literal}, "tweets": ["tweet1", "tweet2", "tweet3", "tweet4"]}}"""

    text = _call_ollama(prompt, 700)

    start = text.find("{")
    end = text.rfind("}") + 1
    if start >= 0 and end > start:
        try:
            obj = json.loads(text[start:end])
            if _valid_thread_payload(obj):
                return obj
        except json.JSONDecodeError:
            pass

    tweets = [
        f"🧵 {hook[:220]}",
        f"1/ {points[0][:250]}" if points else f"1/ {title[:250]}",
        f"2/ {points[1][:240]} 💡" if len(points) > 1 else f"2/ {why[:240]} 💡",
        f"3/ Why it matters: {why[:150]}\n\n{url}\n\n{hashtags}",
    ]
    return {"title": title[:60], "tweets": tweets}


def generate_tweets(processed_json: str) -> str:
    """Generate one engaging Twitter thread per article."""
    summaries = json.loads(processed_json) if processed_json else []
    if not summaries:
        return json.dumps([])

    threads = []
    for i, summary in enumerate(summaries):
        print(
            f"   Generating thread {i + 1}/{len(summaries)}: {summary.get('title', '')[:50]}..."
        )
        thread = _generate_thread_for_article(summary)
        if thread:
            threads.append(thread)

    return json.dumps(threads)


def approve_threads(threads_json: str) -> str:
    """Display threads and ask user which ones to post.

    Preserves the legacy interactive prompt shape, including `q` to stop
    reviewing additional threads while keeping earlier approvals.
    """
    threads = json.loads(threads_json) if threads_json else []
    if not threads:
        print("No threads to review.")
        return json.dumps([])

    print("\n" + "=" * 60)
    print("GENERATED TWEET THREADS")
    print("=" * 60 + "\n")

    approved = []
    for i, thread in enumerate(threads, 1):
        title = thread.get("title", "Untitled")
        tweets = thread.get("tweets", [])

        print(f"\n--- Thread {i}: {title[:50]}{'...' if len(title) > 50 else ''} ---\n")

        for j, tweet in enumerate(tweets, 1):
            prefix = "🧵" if j == 1 else f"{j}/"
            print(f"  {prefix} {tweet}")
            if len(tweet) > 280:
                print(f"     WARNING: {len(tweet)} chars (over 280)")

        print()
        try:
            response = input("Post this thread? (y/n/q): ").strip().lower()
        except EOFError:
            response = "n"

        if response == "y":
            approved.append(thread)
            print("  Approved")
        elif response == "q":
            print("  Quitting...")
            break
        else:
            print("  Skipped")

    print("\n" + "=" * 60)
    print(f"APPROVED: {len(approved)}/{len(threads)} threads")
    print("=" * 60 + "\n")

    return json.dumps(approved)


async def post_to_twitter(
    approved_json: str, twitter_credential_ref: str | None = None
) -> str:
    """Post approved threads via Playwright automation."""
    threads = json.loads(approved_json) if approved_json else []
    if not threads:
        print("No threads to post.")
        return json.dumps({"success": False, "error": "No threads"})

    print(f"\nPosting {len(threads)} thread(s) via Playwright automation...")
    print("Browser will open. First run requires manual login.\n")

    from .twitter import post_threads_impl

    credential_ref = twitter_credential_ref or os.environ.get("TWITTER_CREDENTIAL_REF")
    result = await post_threads_impl(approved_json, None, credential_ref=credential_ref)
    return (
        json.dumps(result)
        if isinstance(result, dict)
        else json.dumps({"success": False, "error": str(result)})
    )
