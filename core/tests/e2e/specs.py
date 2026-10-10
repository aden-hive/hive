"""Synthetic task specs for the end-to-end queen suite.

A spec is data: the user turns, what to plant before the queen boots
(``seed``: files and past sessions; ``resume``: an in-progress
conversation to restore), and a ``check`` that judges the outcome from
disk and the event stream against ground truth from the seed. Add a
scenario by adding a :class:`Spec` to :data:`SPECS`.
"""

from __future__ import annotations

import csv
import hashlib
import json
import subprocess
import sys
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any

from tests.e2e import synthetic


@dataclass(frozen=True)
class Spec:
    id: str
    turns: tuple[str, ...]
    check: Callable[[Any], None]
    seed: Callable[[Path, Path], Any] | None = None
    resume: Callable[[Path], Awaitable[None]] | None = None
    queen_id: str = "queen_technology"
    colony: str | None = None


# ---------------------------------------------------------------------------
# Check helpers
# ---------------------------------------------------------------------------


def _read_json(run: Any, name: str) -> Any:
    path = run.workdir / name
    assert path.is_file(), f"{name} was not written. {run.summary()}"
    return json.loads(path.read_text(encoding="utf-8"))


def _pytest(cwd: Path, *targets: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [sys.executable, "-m", "pytest", "-q", "--no-header", "-p", "no:cacheprovider", *targets],
        cwd=cwd,
        capture_output=True,
        text=True,
        timeout=120,
    )


def _no_tool_errors(run: Any) -> None:
    errored = [(c.name, str(c.result)[:200]) for c in run.tool_calls if c.is_error]
    assert not errored, f"tool calls errored: {errored}"


def _sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


# ---------------------------------------------------------------------------
# Specs
# ---------------------------------------------------------------------------


def _check_files_roundtrip(run: Any) -> None:
    assert run.registry is not None and run.registry._mcp_clients == [], "a bundled tool group started as an MCP subprocess"
    target = run.workdir / "harness_check.txt"
    assert target.is_file(), run.summary()
    assert target.read_text(encoding="utf-8").strip() == "harness-ok-7341"
    assert "harness-ok-7341" in run.text, run.summary()


def _seed_secret_image(workdir: Path, _home: Path) -> None:
    from PIL import Image, ImageDraw, ImageFont

    image = Image.new("RGB", (640, 320), "white")
    ImageDraw.Draw(image).text((60, 70), "4817", fill="black", font=ImageFont.load_default(size=150))
    image.save(workdir / "secret.png")


def _check_vision(run: Any) -> None:
    assert run.called("attach_file"), run.summary()
    assert "4817" in run.text, f"could not read the image. {run.summary()}"


def _check_sales_report(run: Any) -> None:
    truth = run.truth
    report = _read_json(run, "report.json")
    got = {str(k).strip().title(): float(v) for k, v in report["revenue_by_region"].items()}
    assert set(got) == set(truth["revenue_by_region"]), got
    for region, expected in truth["revenue_by_region"].items():
        assert abs(got[region] - expected) <= 0.011, f"{region}: {got[region]} != {expected}"
    assert str(report["top_product_by_units"]).strip().lower() == truth["top_product_by_units"].lower()
    assert str(report["best_month"]).strip() == truth["best_month"]


def _check_incident(run: Any) -> None:
    truth = run.truth
    incident = _read_json(run, "incident.json")
    first = str(incident["first_5xx_at"]).replace("Z", "").replace("+00:00", "").replace(" ", "T")
    assert first == truth["first_5xx_at"], f"first_5xx_at {first} != {truth['first_5xx_at']}"
    assert incident["endpoint_most_5xx"] == truth["endpoint_most_5xx"]
    assert int(incident["count_5xx"]) == truth["count_5xx"]
    assert incident["offending_client_ip"] == truth["offending_client_ip"]


def _seed_bugfix(workdir: Path, _home: Path) -> dict[str, Any]:
    truth = synthetic.buggy_package(workdir)
    truth["visible_sha"] = _sha(workdir / "tests" / "test_totals.py")
    return truth


def _check_bugfix(run: Any) -> None:
    truth = run.truth
    visible = run.workdir / "tests" / "test_totals.py"
    assert visible.is_file() and _sha(visible) == truth["visible_sha"], "the visible tests were edited"
    hidden = run.workdir / "tests" / "test_hidden_e2e.py"
    hidden.write_text(truth["hidden_tests"], encoding="utf-8")
    result = _pytest(run.workdir, "tests")
    assert result.returncode == 0, f"suite still fails:\n{result.stdout[-2000:]}\n{run.summary()}"


def _check_feature(run: Any) -> None:
    assert (run.workdir / "timeparse.py").is_file(), run.summary()
    (run.workdir / "test_hidden_e2e.py").write_text(run.truth["hidden_tests"], encoding="utf-8")
    result = _pytest(run.workdir, "test_hidden_e2e.py")
    assert result.returncode == 0, f"hidden spec tests fail:\n{result.stdout[-2000:]}"


def _seed_past_sessions(_workdir: Path, home: Path) -> None:
    now = datetime.now().replace(microsecond=0)
    synthetic.past_session(
        home,
        "queen_technology",
        started_at=now - timedelta(days=9),
        turns=[
            ("user", "Notes from the Acme onboarding call, keep these handy."),
            (
                "assistant",
                "Noted. Acme's rules for production changes: deploys only on Tuesdays between 02:00 and 04:00 UTC, "
                "and never during their quarter-end freeze (the last 5 business days of each quarter). "
                "Their on-call contact is Priya Raman.",
            ),
            ("user", "Great, thanks."),
        ],
    )
    synthetic.past_session(
        home,
        "queen_technology",
        started_at=now - timedelta(days=3),
        turns=[
            ("user", "Globex wants to know when we can ship the patch."),
            ("assistant", "Globex's change window is Thursdays from 22:00 UTC. I'll plan the patch for this Thursday."),
        ],
    )


def _check_memory_recall(run: Any) -> None:
    # The window can't be guessed, so a right answer means it came from
    # memory: a search_messages call, or the excerpts recalled automatically
    # ahead of the turn.
    text = run.text.lower()
    assert "tuesday" in text and "02:00" in run.text, f"wrong or missing window. {run.summary()}"


def _seed_colony_history(_workdir: Path, home: Path) -> None:
    now = datetime.now().replace(microsecond=0)
    synthetic.past_session(
        home,
        "queen_technology",
        colony="checkout_perf",
        started_at=now - timedelta(days=6),
        turns=[
            ("user", "Run the load test against the checkout service and tell me where it breaks."),
            (
                "worker_tool",
                "k6 run checkout.js: ramp 500->3000 rps. p95 latency 412ms at 2000 rps. Error budget (0.5% 5xx) "
                "exhausted at 2400 rps; connection pool saturation in payments-db at that point.",
            ),
            ("assistant", "The load test is done; I've filed the results with the team."),
        ],
    )
    # A DM the colony must not see: different service, different numbers.
    synthetic.past_session(
        home,
        "queen_technology",
        started_at=now - timedelta(days=2),
        turns=[("user", "Separate thing: the search service load test broke at 900 rps."), ("assistant", "Noted.")],
    )


def _check_colony_memory(run: Any) -> None:
    assert run.called("search_messages"), f"answered without searching memory. {run.summary()}"
    assert "2400" in run.text.replace(",", ""), f"wrong or missing rate. {run.summary()}"
    assert "900" not in run.text, f"used the queen's DM memory, not the colony's. {run.summary()}"


async def _resume_ledger_setup(workdir: Path) -> None:
    await synthetic.in_progress_session(
        workdir,
        [
            {
                "role": "user",
                "content": "We're setting up the ledger-sync service. Use port 8443, service name ledger-sync, and log "
                "level warn. Don't write any files yet, I still need to confirm the region.",
            },
            {
                "role": "assistant",
                "content": "",
                "tool_calls": [
                    {"id": "call_ls1", "type": "function", "function": {"name": "terminal_exec", "arguments": json.dumps({"command": "ls"})}}
                ],
            },
            {"role": "tool", "tool_use_id": "call_ls1", "content": json.dumps({"exit_code": 0, "stdout": "", "stderr": ""})},
            {
                "role": "assistant",
                "content": "Got it: port 8443, service name ledger-sync, log level warn. The working directory is empty, "
                "so nothing to clean up. I'll wait for the region before writing anything.",
            },
        ],
    )


def _check_resume(run: Any) -> None:
    path = run.workdir / "deploy.env"
    assert path.is_file(), f"deploy.env not written. {run.summary()}"
    values: dict[str, str] = {}
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if line and not line.startswith("#") and "=" in line:
            key, _, value = line.partition("=")
            values[key.strip().upper()] = value.strip().strip("\"'")
    assert values.get("PORT") == "8443", values
    assert values.get("SERVICE_NAME") == "ledger-sync", values
    assert values.get("LOG_LEVEL", "").lower() == "warn", values
    assert values.get("REGION") == "eu-west-2", values


def _check_followup(run: Any) -> None:
    truth = run.truth["revenue_by_region"]
    expected_order = sorted(truth, key=truth.__getitem__, reverse=True)
    for name in ("region_totals.csv", "region_totals_v2.csv"):
        assert (run.workdir / name).is_file(), f"{name} missing. {run.summary()}"
    with (run.workdir / "region_totals_v2.csv").open(encoding="utf-8") as fh:
        rows = list(csv.DictReader(fh))
    assert [r["region"].strip().title() for r in rows] == expected_order, rows
    total = sum(truth.values())
    for row in rows:
        region = row["region"].strip().title()
        assert abs(float(row["revenue"]) - truth[region]) <= 0.011, row
        assert abs(float(row["share"]) - truth[region] / total) <= 0.00011, row


SPECS: tuple[Spec, ...] = (
    Spec(
        id="files_roundtrip",
        turns=(
            "In your working directory, create a file named harness_check.txt whose entire content is the text "
            "harness-ok-7341. Then read the file back and reply with its exact contents and nothing else.",
        ),
        check=_check_files_roundtrip,
    ),
    Spec(
        id="vision_attach",
        turns=(
            "There is an image file named secret.png in your working directory. Look at it with attach_file and tell "
            "me the 4-digit number written in it. Reply with just the number.",
        ),
        seed=_seed_secret_image,
        check=_check_vision,
    ),
    Spec(
        id="sales_analysis",
        turns=(
            "sales.csv in your working directory has our 2026-H1 order lines; revenue for a line is units x unit_price. "
            "Write report.json with three keys: revenue_by_region (region -> total revenue, rounded to cents), "
            "top_product_by_units (the product with the most units sold), and best_month (YYYY-MM with the highest "
            "revenue). Compute everything from the data; don't estimate.",
        ),
        seed=lambda workdir, _home: synthetic.sales_csv(workdir / "sales.csv"),
        check=_check_sales_report,
    ),
    Spec(
        id="log_forensics",
        turns=(
            "access.log in your working directory is yesterday's API access log (timestamps are UTC), and there was an "
            "incident. Write incident.json with: first_5xx_at (ISO 8601 timestamp of the first 5xx response, no "
            "timezone suffix), endpoint_most_5xx, count_5xx (total 5xx responses in the whole log), and "
            "offending_client_ip (the client with the most 5xx responses).",
        ),
        seed=lambda workdir, _home: synthetic.access_log(workdir / "access.log"),
        check=_check_incident,
    ),
    Spec(
        id="bugfix_with_tests",
        turns=(
            "The test suite in tests/ is failing. Find and fix the bug(s) in the invoicing package so it behaves as its "
            "docstrings describe and the suite passes. Do not modify the tests. Run the tests to confirm.",
        ),
        seed=_seed_bugfix,
        check=_check_bugfix,
    ),
    Spec(
        id="feature_from_spec",
        turns=("Implement what SPEC.md in your working directory describes. Write your own tests for it and run them.",),
        seed=lambda workdir, _home: synthetic.duration_spec(workdir),
        check=_check_feature,
    ),
    Spec(
        id="memory_recall_across_sessions",
        turns=(
            "In one of our earlier conversations, Acme told us when we're allowed to deploy to their environment. "
            "What is their deployment window? Look it up rather than guessing.",
        ),
        seed=_seed_past_sessions,
        check=_check_memory_recall,
    ),
    Spec(
        id="colony_memory_recall",
        turns=(
            "This colony load-tested the checkout service a few days ago. At what request rate did we exhaust "
            "the error budget? Check the colony's history rather than guessing.",
        ),
        seed=_seed_colony_history,
        colony="checkout_perf",
        check=_check_colony_memory,
    ),
    Spec(
        id="resume_in_progress_session",
        turns=(
            "Region is eu-west-2. Now write deploy.env in your working directory with PORT, SERVICE_NAME, LOG_LEVEL "
            "and REGION, using the values we agreed on.",
        ),
        resume=_resume_ledger_setup,
        check=_check_resume,
    ),
    Spec(
        id="multi_turn_followup",
        turns=(
            "Using sales.csv in your working directory (revenue = units x unit_price), write region_totals.csv with "
            "columns region,revenue (revenue rounded to cents), sorted by revenue descending.",
            "Now add a share column (each region's fraction of total revenue, rounded to 4 decimals) and save it as "
            "region_totals_v2.csv, same columns plus share, same order.",
        ),
        seed=lambda workdir, _home: synthetic.sales_csv(workdir / "sales.csv"),
        check=_check_followup,
    ),
)
