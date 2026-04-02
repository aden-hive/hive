#!/usr/bin/env python3
"""Runner for Level 2 dummy agent tests with interactive LLM provider selection.

This is NOT part of regular CI. It makes real LLM API calls.

Usage:
    cd core && uv run python tests/dummy_agents/run_all.py
    cd core && uv run python tests/dummy_agents/run_all.py --verbose
"""

from __future__ import annotations

import asyncio
import os
import sys
import time
import xml.etree.ElementTree as ET
from pathlib import Path
from tempfile import NamedTemporaryFile, TemporaryDirectory

TESTS_DIR = Path(__file__).parent

# ── provider registry ────────────────────────────────────────────────

# (env_var, display_name, litellm_model, display_model)
# display_model matches quickstart.sh labels; litellm_model is what LiteLLMProvider needs.
API_KEY_PROVIDERS = [
    ("ANTHROPIC_API_KEY", "Anthropic (Claude)", "claude-sonnet-4-20250514", "claude-sonnet-4-20250514"),
    ("OPENAI_API_KEY", "OpenAI", "gpt-5-mini", "gpt-5-mini"),
    ("GEMINI_API_KEY", "Google Gemini", "gemini/gemini-3-flash-preview", "gemini/gemini-3-flash-preview"),
    ("KIMI_API_KEY", "Kimi", "kimi/kimi-k2.5", "kimi-k2.5"),
    ("ZAI_API_KEY", "ZAI (GLM)", "openai/glm-5", "openai/glm-5"),
    ("GROQ_API_KEY", "Groq", "moonshotai/kimi-k2-instruct-0905", "moonshotai/kimi-k2-instruct-0905"),
    ("MISTRAL_API_KEY", "Mistral", "mistral-large-latest", "mistral-large-latest"),
    ("CEREBRAS_API_KEY", "Cerebras", "cerebras/zai-glm-4.7", "cerebras/zai-glm-4.7"),
    ("TOGETHER_API_KEY", "Together AI", "together_ai/meta-llama/Llama-3.3-70B-Instruct-Turbo", "together_ai/meta-llama/Llama-3.3-70B-Instruct-Turbo"),
    ("DEEPSEEK_API_KEY", "DeepSeek", "deepseek-chat", "deepseek-chat"),
    ("MINIMAX_API_KEY", "MiniMax", "MiniMax-M2.5", "MiniMax-M2.5"),
    ("HIVE_API_KEY", "Hive LLM", "hive/queen", "hive/queen"),
]


def _detect_claude_code_token() -> str | None:
    """Check if Claude Code subscription credentials are available."""
    try:
        from framework.runner.runner import get_claude_code_token

        return get_claude_code_token()
    except Exception:
        return None


def _detect_codex_token() -> str | None:
    """Check if Codex subscription credentials are available."""
    try:
        from framework.runner.runner import get_codex_token

        return get_codex_token()
    except Exception:
        return None


def _detect_kimi_code_token() -> str | None:
    """Check if Kimi Code subscription credentials are available."""
    try:
        from framework.runner.runner import get_kimi_code_token

        return get_kimi_code_token()
    except Exception:
        return None


def detect_available() -> list[dict]:
    """Detect all available LLM providers with valid credentials.

    Returns list of dicts: {name, model, api_key, source}
    """
    available = []

    # Subscription-based providers
    token = _detect_claude_code_token()
    if token:
        available.append(
            {
                "name": "Claude Code (subscription)",
                "model": "claude-sonnet-4-20250514",
                "display_model": "claude-sonnet-4-20250514",
                "api_key": token,
                "source": "claude_code_sub",
                "extra_headers": {"authorization": f"Bearer {token}"},
            }
        )

    token = _detect_codex_token()
    if token:
        available.append(
            {
                "name": "Codex (subscription)",
                "model": "gpt-5-mini",
                "display_model": "gpt-5-mini",
                "api_key": token,
                "source": "codex_sub",
            }
        )

    token = _detect_kimi_code_token()
    if token:
        available.append(
            {
                "name": "Kimi Code (subscription)",
                # Quickstart displays "kimi-k2.5", but LiteLLMProvider needs the
                # provider-prefixed form to route through the Kimi coding endpoint.
                "model": "kimi/kimi-k2.5",
                "display_model": "kimi-k2.5",
                "api_key": token,
                "source": "kimi_sub",
                "api_base": "https://api.kimi.com/coding",
            }
        )

    # API key providers (env vars)
    for env_var, name, default_model, display_model in API_KEY_PROVIDERS:
        key = os.environ.get(env_var)
        if key:
            entry = {
                "name": f"{name} (${env_var})",
                "model": default_model,
                "display_model": display_model,
                "api_key": key,
                "source": env_var,
            }
            # ZAI requires an api_base (OpenAI-compatible endpoint)
            if env_var == "ZAI_API_KEY":
                entry["api_base"] = "https://api.z.ai/api/coding/paas/v4"
            # Kimi Code uses the coding endpoint selected by quickstart.
            elif env_var == "KIMI_API_KEY":
                entry["api_base"] = "https://api.kimi.com/coding"
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
        print("    export KIMI_API_KEY=...")
        print("  Or authenticate with Claude Code: claude")
        print("  Or authenticate with Kimi Code: kimi /login")
        sys.exit(1)

    if len(available) == 1:
        choice = available[0]
        print(f"\n  Using: {choice['name']} ({choice.get('display_model', choice['model'])})")
        return choice

    print("\n  Available LLM providers:\n")
    for i, p in enumerate(available, 1):
        print(f"    {i}) {p['name']}  [{p.get('display_model', p['model'])}]")

    print()
    while True:
        try:
            raw = input(f"  Select provider [1-{len(available)}]: ").strip()
            idx = int(raw) - 1
            if 0 <= idx < len(available):
                choice = available[idx]
                print(
                    f"\n  Using: {choice['name']} "
                    f"({choice.get('display_model', choice['model'])})\n"
                )
                return choice
        except (ValueError, EOFError):
            pass
        print(f"  Please enter a number between 1 and {len(available)}")


async def _smoke_test_provider_async(provider: dict, timeout_seconds: float = 25.0) -> None:
    """Fail fast if the selected provider cannot complete a tiny request.

    This catches the common "pytest looks frozen on the first test" failure mode
    where the first real LLM call hangs or never reaches a usable response.
    """
    from framework.llm.litellm import LiteLLMProvider
    from framework.llm.provider import Tool
    from framework.graph.edge import GraphSpec
    from framework.graph.executor import GraphExecutor
    from framework.graph.goal import Goal
    from framework.graph.node import NodeSpec
    from framework.runtime.core import Runtime

    kwargs = {
        "model": provider["model"],
        "api_key": provider["api_key"],
    }
    if provider.get("api_base"):
        kwargs["api_base"] = provider["api_base"]
    if provider.get("extra_headers"):
        kwargs["extra_headers"] = provider["extra_headers"]

    llm = LiteLLMProvider(**kwargs)

    async def _run_plain_completion() -> None:
        result = await llm.acomplete(
            messages=[{"role": "user", "content": "Reply with exactly OK."}],
            max_tokens=8,
        )
        content = (result.content or "").strip()
        if not content:
            raise RuntimeError("provider returned an empty completion during smoke test")

    async def _run_tool_completion() -> None:
        tool = Tool(
            name="record_result",
            description="Record the final result string.",
            parameters={
                "properties": {
                    "value": {
                        "type": "string",
                        "description": "The result to record.",
                    }
                },
                "required": ["value"],
            },
        )
        response = await llm.acomplete(
            messages=[
                {
                    "role": "user",
                    "content": (
                        "Call the record_result tool exactly once with value='OK'. "
                        "Do not answer with plain text."
                    ),
                }
            ],
            tools=[tool],
            max_tokens=32,
        )

        raw = response.raw_response
        tool_calls = []
        if raw is not None and getattr(raw, "choices", None):
            msg = raw.choices[0].message
            tool_calls = msg.tool_calls or []

        if not tool_calls:
            raise RuntimeError("provider completed but did not return any tool calls")

    async def _run_worker_execution() -> None:
        with TemporaryDirectory(prefix="dummy-worker-smoke-") as tmpdir:
            tmp_path = Path(tmpdir)
            runtime = Runtime(storage_path=tmp_path / "runtime")
            executor = GraphExecutor(
                runtime=runtime,
                llm=llm,
                storage_path=tmp_path / "session",
                loop_config={"max_iterations": 4},
            )
            graph = GraphSpec(
                id="dummy-worker-smoke",
                goal_id="dummy-worker-smoke-goal",
                entry_node="worker",
                entry_points={"start": "worker"},
                terminal_nodes=["worker"],
                nodes=[
                    NodeSpec(
                        id="worker",
                        name="Worker Smoke Test",
                        description="Minimal worker-path smoke test",
                        node_type="event_loop",
                        input_keys=["task"],
                        output_keys=["result"],
                        system_prompt=(
                            "You are a worker test node. Read the 'task' input. "
                            "You MUST call set_output with key='result' and value='OK'. "
                            "Do not use plain text as the final answer."
                        ),
                    )
                ],
                edges=[],
                memory_keys=["task", "result"],
                conversation_mode="continuous",
            )
            goal = Goal(
                id="dummy-worker-smoke-goal",
                name="Dummy Worker Smoke",
                description="Verify the current worker execution implementation can finish.",
            )
            result = await executor.execute(
                graph,
                goal,
                {"task": "Return OK by calling set_output."},
                validate_graph=False,
            )
            if not result.success:
                raise RuntimeError(result.error or "worker execution smoke failed")
            if result.output.get("result") != "OK":
                raise RuntimeError(
                    "worker execution completed but did not produce result='OK'"
                )

    async def _run_branch_execution() -> None:
        with TemporaryDirectory(prefix="dummy-branch-smoke-") as tmpdir:
            tmp_path = Path(tmpdir)
            runtime = Runtime(storage_path=tmp_path / "runtime")
            executor = GraphExecutor(
                runtime=runtime,
                llm=llm,
                storage_path=tmp_path / "session",
                loop_config={"max_iterations": 4},
            )
            graph = GraphSpec(
                id="dummy-branch-smoke",
                goal_id="dummy-branch-smoke-goal",
                entry_node="classify",
                entry_points={"start": "classify"},
                terminal_nodes=["positive", "negative"],
                nodes=[
                    NodeSpec(
                        id="classify",
                        name="Branch Classifier",
                        description="Routes to the positive or negative handler",
                        node_type="event_loop",
                        input_keys=["route"],
                        output_keys=["label"],
                        system_prompt=(
                            "Read the 'route' input. "
                            "If it is exactly 'positive', call set_output with "
                            "key='label' and value='positive'. "
                            "Otherwise call set_output with key='label' and value='negative'. "
                            "Do not use plain text as the final answer."
                        ),
                    ),
                    NodeSpec(
                        id="positive",
                        name="Positive Branch",
                        description="Positive terminal branch",
                        node_type="event_loop",
                        output_keys=["result"],
                        system_prompt=(
                            "Call set_output with key='result' and value='BRANCH_OK'. "
                            "Do not use plain text as the final answer."
                        ),
                    ),
                    NodeSpec(
                        id="negative",
                        name="Negative Branch",
                        description="Negative terminal branch",
                        node_type="event_loop",
                        output_keys=["result"],
                        system_prompt=(
                            "Call set_output with key='result' and value='UNEXPECTED_NEGATIVE'. "
                            "Do not use plain text as the final answer."
                        ),
                    ),
                ],
                edges=[
                    {
                        "id": "classify-to-positive",
                        "source": "classify",
                        "target": "positive",
                        "condition": "conditional",
                        "condition_expr": "output.get('label') == 'positive'",
                        "priority": 1,
                    },
                    {
                        "id": "classify-to-negative",
                        "source": "classify",
                        "target": "negative",
                        "condition": "conditional",
                        "condition_expr": "output.get('label') == 'negative'",
                        "priority": 0,
                    },
                ],
                memory_keys=["route", "label", "result"],
                conversation_mode="continuous",
            )
            goal = Goal(
                id="dummy-branch-smoke-goal",
                name="Dummy Branch Smoke",
                description="Verify conditional worker routing reaches the expected terminal.",
            )
            result = await executor.execute(
                graph,
                goal,
                {"route": "positive"},
                validate_graph=False,
            )
            if not result.success:
                raise RuntimeError(result.error or "branch execution smoke failed")
            if result.path != ["classify", "positive"]:
                raise RuntimeError(
                    "branch execution did not reach the expected terminal path: "
                    f"{result.path}"
                )
            if not result.output.get("result"):
                raise RuntimeError(
                    "branch execution reached the expected terminal path but did not "
                    f"produce a non-empty result output: path={result.path} "
                    f"output={result.output}"
                )

    current_step = "plain completion"
    current_timeout = timeout_seconds
    worker_timeout = max(
        timeout_seconds,
        float(os.environ.get("DUMMY_AGENT_SMOKE_WORKER_TIMEOUT_SECS", "30")),
    )
    branch_timeout = max(
        timeout_seconds,
        float(os.environ.get("DUMMY_AGENT_SMOKE_BRANCH_TIMEOUT_SECS", "60")),
    )

    try:
        await asyncio.wait_for(_run_plain_completion(), timeout=current_timeout)
        current_step = "tool calling"
        current_timeout = timeout_seconds
        await asyncio.wait_for(_run_tool_completion(), timeout=current_timeout)
        current_step = "single-node worker execution"
        current_timeout = worker_timeout
        await asyncio.wait_for(_run_worker_execution(), timeout=current_timeout)
        current_step = "branch worker execution"
        current_timeout = branch_timeout
        await asyncio.wait_for(_run_branch_execution(), timeout=current_timeout)
    except TimeoutError as exc:
        raise RuntimeError(
            f"provider smoke test timed out during {current_step} "
            f"after {current_timeout:.0f}s"
        ) from exc


def smoke_test_provider(provider: dict, timeout_seconds: float = 25.0) -> None:
    """Run a tiny real completion before starting pytest."""
    print("  Running provider smoke test...", end=" ", flush=True)
    started = time.time()
    try:
        asyncio.run(_smoke_test_provider_async(provider, timeout_seconds=timeout_seconds))
    except TimeoutError:
        print("FAILED")
        print(
            "  The selected provider did not complete a tiny request within "
            f"{timeout_seconds:.0f}s."
        )
        print(
            "  This usually means the provider is unreachable, rate-limited, "
            "or hanging on the selected model/API base."
        )
        sys.exit(1)
    except Exception as e:
        print("FAILED")
        print(f"  Provider smoke test failed: {type(e).__name__}: {e}")
        sys.exit(1)

    elapsed = time.time() - started
    print(f"OK ({elapsed:.1f}s)")


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
    smoke_test_provider(provider)

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
