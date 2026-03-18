#!/usr/bin/env python3
"""Runner for Level 2 dummy agent tests with interactive LLM provider selection.

This is NOT part of regular CI. It makes real LLM API calls.

Usage:
    cd core && uv run python tests/dummy_agents/run_all.py
    cd core && uv run python tests/dummy_agents/run_all.py --verbose
"""

from __future__ import annotations

import os
import sys
import time
import xml.etree.ElementTree as ET
from pathlib import Path
from tempfile import NamedTemporaryFile

TESTS_DIR = Path(__file__).parent

# ── provider registry ────────────────────────────────────────────────

# (env_var, display_name, default_model) — models match quickstart.sh defaults
API_KEY_PROVIDERS = [
    ("ANTHROPIC_API_KEY", "Anthropic (Claude)", "claude-sonnet-4-20250514"),
    ("OPENAI_API_KEY", "OpenAI", "gpt-5-mini"),
    ("GEMINI_API_KEY", "Google Gemini", "gemini/gemini-3-flash-preview"),
    ("ZAI_API_KEY", "ZAI (GLM)", "openai/glm-5"),
    ("GROQ_API_KEY", "Groq", "moonshotai/kimi-k2-instruct-0905"),
    ("MISTRAL_API_KEY", "Mistral", "mistral-large-latest"),
    ("CEREBRAS_API_KEY", "Cerebras", "cerebras/zai-glm-4.7"),
    ("TOGETHER_API_KEY", "Together AI", "together_ai/meta-llama/Llama-3.3-70B-Instruct-Turbo"),
    ("DEEPSEEK_API_KEY", "DeepSeek", "deepseek-chat"),
    ("MINIMAX_API_KEY", "MiniMax", "MiniMax-M2.5"),
    ("HIVE_API_KEY", "Hive LLM", "hive/queen"),
]


def detect_available() -> list[dict]:
    """Detect all available LLM providers with valid credentials.

    Returns list of dicts: {name, model, api_key, source}
    """
    available = []

    # API key providers (env vars)
    for env_var, name, default_model in API_KEY_PROVIDERS:
        key = os.environ.get(env_var)
        if key:
            entry = {
                "name": f"{name} (${env_var})",
                "model": default_model,
                "api_key": key,
                "source": env_var,
            }
            # ZAI requires an api_base (OpenAI-compatible endpoint)
            if env_var == "ZAI_API_KEY":
                entry["api_base"] = "https://api.z.ai/api/coding/paas/v4"
            available.append(entry)

    return available


def prompt_provider_selection() -> dict:
    """Interactive prompt to select an LLM provider. Returns the chosen provider dict."""
    available = detect_available()

    if not available:
        print("\n  No LLM credentials detected.")
        print("  Set an API key environment variable, e.g.:")
        print("    export ANTHROPIC_API_KEY=sk-...")
        print("    export OPENAI_API_KEY=sk-...")
        print("  Or authenticate with Claude Code: claude")
        sys.exit(1)

    if len(available) == 1:
        choice = available[0]
        print(f"\n  Using: {choice['name']} ({choice['model']})")
        return choice

    print("\n  Available LLM providers:\n")
    for i, p in enumerate(available, 1):
        print(f"    {i}) {p['name']}  [{p['model']}]")

    print()
    while True:
        try:
            raw = input(f"  Select provider [1-{len(available)}]: ").strip()
            idx = int(raw) - 1
            if 0 <= idx < len(available):
                choice = available[idx]
                print(f"\n  Using: {choice['name']} ({choice['model']})\n")
                return choice
        except (ValueError, EOFError):
            pass
        print(f"  Please enter a number between 1 and {len(available)}")


# ── test runner ──────────────────────────────────────────────────────


def parse_junit_xml(xml_path: str) -> dict[str, dict]:
    """Parse JUnit XML and group results by agent (test file)."""
    tree = ET.parse(xml_path)
    root = tree.getroot()
    agents: dict[str, dict] = {}

    for testsuite in root.iter("testsuite"):
        for testcase in testsuite.iter("testcase"):
            classname = testcase.get("classname", "")
            parts = classname.split(".")
            agent_name = "unknown"
            for part in parts:
                if part.startswith("test_"):
                    agent_name = part[5:]
                    break

            if agent_name not in agents:
                agents[agent_name] = {
                    "total": 0,
                    "passed": 0,
                    "failed": 0,
                    "time": 0.0,
                    "tests": [],
                }

            agents[agent_name]["total"] += 1
            test_time = float(testcase.get("time", "0"))
            agents[agent_name]["time"] += test_time

            failures = testcase.findall("failure")
            errors = testcase.findall("error")
            test_name = testcase.get("name", "")

            if failures or errors:
                agents[agent_name]["failed"] += 1
                # Extract failure reason from the first failure/error element
                fail_el = (failures or errors)[0]
                reason = fail_el.get("message", "") or ""
                # Also grab the text body for more detail
                body = fail_el.text or ""
                # Build a concise reason: prefer message, fall back to first line of body
                if not reason and body:
                    reason = body.strip().split("\n")[0]
                agents[agent_name]["tests"].append((test_name, "FAIL", reason))
            else:
                agents[agent_name]["passed"] += 1
                agents[agent_name]["tests"].append((test_name, "PASS", ""))

    return agents


def print_table(agents: dict[str, dict], total_time: float, verbose: bool = False) -> None:
    """Print summary table."""
    col_agent = 20
    col_tests = 6
    col_passed = 8
    col_time = 12

    def sep(char: str = "═") -> str:
        return (
            f"╠{char * (col_agent + 2)}╬{char * (col_tests + 2)}"
            f"╬{char * (col_passed + 2)}╬{char * (col_time + 2)}╣"
        )

    header = (
        f"║ {'Agent':<{col_agent}} ║ {'Tests':>{col_tests}} "
        f"║ {'Passed':>{col_passed}} ║ {'Time (s)':>{col_time}} ║"
    )
    top = (
        f"╔{'═' * (col_agent + 2)}╦{'═' * (col_tests + 2)}"
        f"╦{'═' * (col_passed + 2)}╦{'═' * (col_time + 2)}╗"
    )
    bottom = (
        f"╚{'═' * (col_agent + 2)}╩{'═' * (col_tests + 2)}"
        f"╩{'═' * (col_passed + 2)}╩{'═' * (col_time + 2)}╝"
    )

    print()
    print(top)
    print(header)
    print(sep())

    total_tests = 0
    total_passed = 0

    for agent_name in sorted(agents.keys()):
        data = agents[agent_name]
        total_tests += data["total"]
        total_passed += data["passed"]
        marker = " " if data["failed"] == 0 else "!"
        row = (
            f"║{marker}{agent_name:<{col_agent + 1}} ║ {data['total']:>{col_tests}} "
            f"║ {data['passed']:>{col_passed}} ║ {data['time']:>{col_time}.2f} ║"
        )
        print(row)

        if verbose:
            for test_name, status, reason in data["tests"]:
                icon = "  ✓" if status == "PASS" else "  ✗"
                print(
                    f"║   {icon} {test_name:<{col_agent - 2}}"
                    f"║{'':>{col_tests + 2}}║{'':>{col_passed + 2}}║{'':>{col_time + 2}}║"
                )
                if status == "FAIL" and reason:
                    # Print failure reason wrapped to fit, indented under the test
                    reason_short = reason[:120] + ("..." if len(reason) > 120 else "")
                    print(f"║       {reason_short}")
                    print("║")

    print(sep())
    all_pass = total_passed == total_tests
    status = "ALL PASS" if all_pass else f"{total_tests - total_passed} FAILED"
    totals = (
        f"║ {status:<{col_agent}} ║ {total_tests:>{col_tests}} "
        f"║ {total_passed:>{col_passed}} ║ {total_time:>{col_time}.2f} ║"
    )
    print(totals)
    print(bottom)

    # Always print failure details if any tests failed
    if not all_pass:
        print("\n  Failure Details:")
        print("  " + "─" * 70)
        for agent_name in sorted(agents.keys()):
            for test_name, status, reason in agents[agent_name]["tests"]:
                if status == "FAIL":
                    print(f"\n  ✗ {agent_name}::{test_name}")
                    if reason:
                        # Wrap long reasons
                        for i in range(0, len(reason), 100):
                            print(f"    {reason[i : i + 100]}")
        print()


def main() -> int:
    verbose = "--verbose" in sys.argv or "-v" in sys.argv

    print("\n  ╔═══════════════════════════════════════╗")
    print("  ║   Level 2: Dummy Agent Tests (E2E)    ║")
    print("  ╚═══════════════════════════════════════╝")

    # Step 1: detect credentials and let user pick
    provider = prompt_provider_selection()

    # Step 2: inject selection into conftest module state
    from tests.dummy_agents.conftest import set_llm_selection

    set_llm_selection(
        model=provider["model"],
        api_key=provider["api_key"],
        extra_headers=provider.get("extra_headers"),
        api_base=provider.get("api_base"),
    )

    # Step 3: run pytest
    with NamedTemporaryFile(suffix=".xml", delete=False) as tmp:
        xml_path = tmp.name

    start = time.time()
    import pytest as _pytest

    pytest_args = [
        str(TESTS_DIR),
        f"--junitxml={xml_path}",
        "--tb=short",
        "--override-ini=asyncio_mode=auto",
        "--log-cli-level=INFO",  # Stream logs live to terminal
        "-v",
    ]
    if not verbose:
        # In non-verbose mode, only show warnings and above
        pytest_args[pytest_args.index("--log-cli-level=INFO")] = "--log-cli-level=WARNING"
        pytest_args.remove("-v")
        pytest_args.append("-q")

    exit_code = _pytest.main(pytest_args)
    elapsed = time.time() - start

    # Step 4: print summary
    try:
        agents = parse_junit_xml(xml_path)
        print_table(agents, elapsed, verbose=verbose)
    except Exception as e:
        print(f"\n  Could not parse results: {e}")

    # Clean up
    Path(xml_path).unlink(missing_ok=True)

    return exit_code


if __name__ == "__main__":
    sys.exit(main())
