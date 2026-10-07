"""Synthetic workspaces and sessions for end-to-end queen specs.

Every generator is deterministic for a given seed and returns the ground
truth its spec checks against, so a spec never trusts the agent's own
account of what it did.

Sessions are written in the formats the runtime itself reads:

* past sessions: ``events.jsonl`` under ``$HIVE_HOME/queens/<id>/sessions/``,
  the event shapes the bus persists (what ``search_messages`` indexes);
* in-progress sessions: a conversation store written through the real
  ``NodeConversation`` / ``FileConversationStore`` API, which the queen
  restores on resume.
"""

from __future__ import annotations

import csv
import json
import random
import textwrap
import uuid
from collections import Counter, defaultdict
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any

# ---------------------------------------------------------------------------
# Workspaces
# ---------------------------------------------------------------------------

_REGIONS = ("North", "South", "East", "West")
_PRODUCTS = {"Widget": 12.50, "Gadget": 31.00, "Gizmo": 7.25, "Doohickey": 54.90, "Sprocket": 3.10}


def sales_csv(path: Path, *, seed: int = 7, rows: int = 480) -> dict[str, Any]:
    """Order lines for 2026-H1. Truth: revenue by region, top product, best month."""
    rng = random.Random(seed)
    revenue_by_region: dict[str, float] = defaultdict(float)
    units_by_product: Counter[str] = Counter()
    revenue_by_month: dict[str, float] = defaultdict(float)
    start = datetime(2026, 1, 1)
    with path.open("w", newline="", encoding="utf-8") as fh:
        writer = csv.writer(fh)
        writer.writerow(["order_id", "date", "region", "product", "units", "unit_price"])
        for i in range(rows):
            day = start + timedelta(days=rng.randrange(181))
            region = rng.choice(_REGIONS)
            product = rng.choice(list(_PRODUCTS))
            units = rng.randint(1, 40)
            price = _PRODUCTS[product]
            writer.writerow([f"SO-{10000 + i}", day.date().isoformat(), region, product, units, f"{price:.2f}"])
            revenue = units * price
            revenue_by_region[region] += revenue
            units_by_product[product] += units
            revenue_by_month[day.strftime("%Y-%m")] += revenue
    return {
        "revenue_by_region": {r: round(v, 2) for r, v in revenue_by_region.items()},
        "top_product_by_units": units_by_product.most_common(1)[0][0],
        "best_month": max(revenue_by_month, key=revenue_by_month.__getitem__),
    }


def access_log(path: Path, *, seed: int = 11, lines: int = 6000) -> dict[str, Any]:
    """A day of access logs with one incident. Truth: when/where/who."""
    rng = random.Random(seed)
    endpoints = ["/api/orders", "/api/users", "/api/cart", "/api/search", "/healthz"]
    clients = [f"10.0.{rng.randint(0, 9)}.{rng.randint(2, 250)}" for _ in range(40)]
    offender = "203.0.113.77"
    incident_start = datetime(2026, 3, 14, 13, 37, 5)
    t = datetime(2026, 3, 14, 0, 0, 0)
    first_5xx: datetime | None = None
    errors_by_endpoint: Counter[str] = Counter()
    errors_by_client: Counter[str] = Counter()
    with path.open("w", encoding="utf-8") as fh:
        for _ in range(lines):
            t += timedelta(seconds=rng.randint(5, 20))
            in_incident = incident_start <= t < incident_start + timedelta(minutes=25)
            if in_incident and rng.random() < 0.55:
                client, endpoint = offender, "/api/cart"
                status = rng.choice([500, 502, 503])
            else:
                client, endpoint = rng.choice(clients), rng.choice(endpoints)
                status = rng.choices([200, 201, 304, 404], weights=[80, 5, 10, 5])[0]
            if status >= 500:
                first_5xx = first_5xx or t
                errors_by_endpoint[endpoint] += 1
                errors_by_client[client] += 1
            fh.write(f'{client} - - [{t:%d/%b/%Y:%H:%M:%S} +0000] "GET {endpoint} HTTP/1.1" {status} {rng.randint(120, 9000)}\n')
    assert first_5xx is not None
    return {
        "first_5xx_at": first_5xx.strftime("%Y-%m-%dT%H:%M:%S"),
        "endpoint_most_5xx": errors_by_endpoint.most_common(1)[0][0],
        "count_5xx": sum(errors_by_endpoint.values()),
        "offending_client_ip": errors_by_client.most_common(1)[0][0],
    }


def buggy_package(root: Path) -> dict[str, Any]:
    """A small invoicing package whose visible tests fail on a real bug.

    Truth carries hidden tests (never shown to the agent) and the visible
    test file's original text, so the check can tell "fixed the code" from
    "edited the tests".
    """
    pkg = root / "invoicing"
    pkg.mkdir()
    (pkg / "__init__.py").write_text("", encoding="utf-8")
    (pkg / "totals.py").write_text(
        textwrap.dedent(
            '''\
            """Invoice totals. Amounts are integer cents."""


            def line_total(unit_cents: int, qty: int, discount_pct: float = 0.0) -> int:
                """Price of one line after its percentage discount, rounded half-up to a cent."""
                gross = unit_cents * qty
                return int(gross - gross * discount_pct)


            def invoice_total(lines: list[dict], tax_rate: float) -> int:
                """Sum of line totals plus tax on that sum, rounded half-up to a cent."""
                subtotal = 0
                for line in lines:
                    subtotal = line_total(line["unit_cents"], line["qty"], line.get("discount_pct", 0.0))
                return round(subtotal * (1 + tax_rate))
            '''
        ),
        encoding="utf-8",
    )
    tests = root / "tests"
    tests.mkdir()
    visible = textwrap.dedent(
        """\
        from invoicing.totals import invoice_total, line_total


        def test_line_total_discount_is_a_percentage():
            assert line_total(1000, 3, discount_pct=10) == 2700


        def test_invoice_total_sums_every_line():
            lines = [{"unit_cents": 500, "qty": 2}, {"unit_cents": 250, "qty": 4}]
            assert invoice_total(lines, tax_rate=0.0) == 2000


        def test_invoice_total_adds_tax():
            assert invoice_total([{"unit_cents": 1000, "qty": 1}], tax_rate=0.08) == 1080
        """
    )
    (tests / "test_totals.py").write_text(visible, encoding="utf-8")
    hidden = textwrap.dedent(
        """\
        from invoicing.totals import invoice_total, line_total


        def test_rounds_half_up_to_the_cent():
            assert line_total(333, 1, discount_pct=50) == 167


        def test_discounts_apply_per_line():
            lines = [
                {"unit_cents": 1999, "qty": 2, "discount_pct": 25},
                {"unit_cents": 500, "qty": 1},
            ]
            assert invoice_total(lines, tax_rate=0.0) == 2999 + 500


        def test_empty_invoice_is_zero():
            assert invoice_total([], tax_rate=0.2) == 0
        """
    )
    return {"visible_tests": visible, "hidden_tests": hidden}


def duration_spec(root: Path) -> dict[str, Any]:
    """A written spec for a function that doesn't exist yet. Truth: hidden tests."""
    (root / "SPEC.md").write_text(
        textwrap.dedent(
            """\
            # parse_duration

            Implement `parse_duration(text: str) -> int` in `timeparse.py` (repo root).
            It returns the duration in whole seconds.

            * Units: `d` (days), `h` (hours), `m` (minutes), `s` (seconds).
            * Units may be combined in descending order: `1h30m`, `2d4h`, `1d2h3m4s`.
            * A bare integer means seconds: `"90"` -> 90.
            * Surrounding whitespace is ignored; whitespace between parts is not allowed.
            * Units are case-insensitive: `1H` == `1h`.
            * Anything else raises `ValueError`: empty string, unknown unit, units out of
              order (`30m1h`), a repeated unit (`1h1h`), negative numbers, decimals.
            """
        ),
        encoding="utf-8",
    )
    hidden = textwrap.dedent(
        """\
        import pytest

        from timeparse import parse_duration


        @pytest.mark.parametrize(
            ("text", "seconds"),
            [("90", 90), ("1h30m", 5400), ("2d4h", 187200), ("1d2h3m4s", 93784), ("  45s ", 45), ("1H", 3600), ("0s", 0)],
        )
        def test_valid(text, seconds):
            assert parse_duration(text) == seconds


        @pytest.mark.parametrize("text", ["", "1x", "30m1h", "1h1h", "-5s", "1.5h", "1h 30m", "h"])
        def test_invalid(text):
            with pytest.raises(ValueError):
                parse_duration(text)
        """
    )
    return {"hidden_tests": hidden}


# ---------------------------------------------------------------------------
# Sessions
# ---------------------------------------------------------------------------


def past_session(
    hive_home: Path,
    queen_id: str,
    *,
    started_at: datetime,
    turns: list[tuple[str, str]],
) -> str:
    """Write a finished DM session's ``events.jsonl``. Returns the session id.

    *turns* are ``(role, text)`` pairs; role is ``user`` or ``assistant``.
    """
    session_id = f"session_{started_at:%Y%m%d_%H%M%S}_{uuid.uuid4().hex[:8]}"
    session_dir = hive_home / "queens" / queen_id / "sessions" / session_id
    session_dir.mkdir(parents=True)
    events: list[dict[str, Any]] = []
    t = started_at
    for iteration, (role, text) in enumerate(turns):
        t += timedelta(minutes=2)
        if role == "user":
            etype, data = "client_input_received", {"content": text, "image_count": 0}
        else:
            etype, data = "client_output_delta", {"content": text, "snapshot": text, "iteration": iteration, "inner_turn": 0}
        events.append(
            {
                "type": etype,
                "stream_id": "queen",
                "node_id": "queen",
                "execution_id": session_id,
                "data": data,
                "timestamp": t.isoformat(),
                "correlation_id": None,
                "colony_id": None,
                "seq": len(events) + 1,
            }
        )
    (session_dir / "events.jsonl").write_text("".join(json.dumps(e) + "\n" for e in events), encoding="utf-8")
    (session_dir / "meta.json").write_text(json.dumps({"phase": "independent", "queen_id": queen_id}), encoding="utf-8")
    return session_id


async def in_progress_session(queen_dir: Path, messages: list[dict[str, Any]]) -> None:
    """Write a resumable conversation into ``queen_dir`` via the real store.

    *messages* entries: ``{"role": "user", "content": ...}``,
    ``{"role": "assistant", "content": ..., "tool_calls": [...]}`` or
    ``{"role": "tool", "tool_use_id": ..., "content": ...}``.
    """
    from framework.agent_loop.conversation import NodeConversation
    from framework.storage.conversation_store import FileConversationStore

    conv = NodeConversation(system_prompt="", store=FileConversationStore(queen_dir / "conversations"))
    for m in messages:
        if m["role"] == "user":
            await conv.add_user_message(m["content"], is_client_input=True)
        elif m["role"] == "assistant":
            await conv.add_assistant_message(m.get("content", ""), tool_calls=m.get("tool_calls"))
        else:
            await conv.add_tool_result(tool_use_id=m["tool_use_id"], content=m["content"])
    (queen_dir / "meta.json").write_text(json.dumps({"phase": "independent"}), encoding="utf-8")
