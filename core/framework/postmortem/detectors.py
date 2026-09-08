"""Detectors that turn runtime logs into ranked findings.

Each detector is a pure function of the loaded run plus a ``Thresholds``
object, and returns zero or more ``Finding``s. Adding a detector means
writing one function and appending it to ``DETECTORS``.

Guiding rule: a clean run must produce an empty list. Thresholds are set so
that anything reported is a real anomaly a human should look at, not a
statistic.
"""

from __future__ import annotations

import hashlib
import json
from collections import Counter, defaultdict
from collections.abc import Callable

from framework.postmortem.models import Finding, Severity, Thresholds
from framework.tracker.runtime_log_schemas import NodeDetail, NodeStepLog

# Node exit statuses that mean the node did not finish its work cleanly.
_BAD_EXITS = {
    "failure": Severity.CRITICAL,
    "guard_failure": Severity.CRITICAL,
    "stalled": Severity.HIGH,
    "escalated": Severity.HIGH,
}


def _fingerprint(tool_name: str, tool_input: dict) -> str:
    """Stable hash of a tool call's identity, for repeat detection."""
    try:
        payload = json.dumps(tool_input, sort_keys=True, ensure_ascii=False, default=str)
    except (TypeError, ValueError):
        payload = repr(tool_input)
    return hashlib.sha1(f"{tool_name}\x00{payload}".encode()).hexdigest()[:12]


def _short(text: str, limit: int = 120) -> str:
    """Collapse whitespace and truncate for a single evidence line."""
    flat = " ".join(str(text).split())
    return flat if len(flat) <= limit else flat[: limit - 1] + "…"


def _label(step: NodeStepLog) -> str:
    return f"{step.node_id}#{step.step_index}"


# ---------------------------------------------------------------------------
# Detectors
# ---------------------------------------------------------------------------


def detect_tool_thrash(nodes: list[NodeDetail], steps: list[NodeStepLog], t: Thresholds) -> list[Finding]:
    """Identical tool call repeated inside one node — the agent is looping.

    Repeating the same tool with byte-identical arguments cannot produce new
    information, so it is the clearest signal of a stuck event loop.
    """
    counts: Counter[tuple[str, str, str]] = Counter()
    for step in steps:
        for call in step.tool_calls:
            counts[(step.node_id, call.tool_name, _fingerprint(call.tool_name, call.tool_input))] += 1

    repeats = [(key, n) for key, n in counts.items() if n >= t.thrash_min_repeats]
    if not repeats:
        return []
    repeats.sort(key=lambda item: item[1], reverse=True)

    findings: list[Finding] = []
    for (node_id, tool_name, fp), n in repeats[: t.max_evidence]:
        severity = Severity.HIGH if n >= t.thrash_high_repeats else Severity.MEDIUM
        findings.append(
            Finding(
                code="tool_thrash",
                title=f"'{tool_name}' called {n}x with identical arguments",
                severity=severity,
                node_id=node_id,
                detail=(
                    f"Node '{node_id}' invoked '{tool_name}' {n} times with byte-identical "
                    "input. Repeated identical calls cannot return new information."
                ),
                suggestion=(
                    "Check the node's exit criteria and whether the tool result is being "
                    "surfaced back into the conversation in a form the model can act on."
                ),
                metrics={"tool": tool_name, "repeats": n, "fingerprint": fp},
            )
        )
    return findings


def detect_failing_tools(nodes: list[NodeDetail], steps: list[NodeStepLog], t: Thresholds) -> list[Finding]:
    """Tools that error often enough to be the run's real bottleneck."""
    calls: Counter[str] = Counter()
    errors: Counter[str] = Counter()
    # Distinct error texts per tool, each with a count. One tool failing the
    # same way 20 times is one line of evidence, not 20.
    messages: dict[str, Counter[str]] = defaultdict(Counter)

    for step in steps:
        for call in step.tool_calls:
            calls[call.tool_name] += 1
            if call.is_error:
                errors[call.tool_name] += 1
                messages[call.tool_name][_short(call.result)] += 1

    findings: list[Finding] = []
    for tool_name, n_err in errors.most_common():
        total = calls[tool_name]
        rate = n_err / total if total else 0.0
        if n_err < t.tool_fail_min_errors or rate < t.tool_fail_min_rate:
            continue
        severity = (
            Severity.HIGH if rate >= t.tool_fail_high_rate and n_err >= t.tool_fail_min_errors + 1 else Severity.MEDIUM
        )
        findings.append(
            Finding(
                code="failing_tool",
                title=f"'{tool_name}' failed {n_err}/{total} calls ({rate:.0%})",
                severity=severity,
                detail=(
                    f"Tool '{tool_name}' returned an error on {n_err} of {total} calls. "
                    "Each failure costs a full model turn to observe and retry."
                ),
                suggestion=(
                    "Check credentials and argument schema for this tool, and consider whether "
                    "the error text tells the model enough to correct itself."
                ),
                evidence=[
                    f"{n}x  {text}" if n > 1 else text for text, n in messages[tool_name].most_common(t.max_evidence)
                ],
                metrics={
                    "tool": tool_name,
                    "errors": n_err,
                    "calls": total,
                    "rate": round(rate, 4),
                    "distinct_errors": len(messages[tool_name]),
                },
            )
        )
    return findings


def detect_retry_storms(nodes: list[NodeDetail], steps: list[NodeStepLog], t: Thresholds) -> list[Finding]:
    """Nodes whose judge kept sending work back, or that were re-attempted."""
    findings: list[Finding] = []
    attempts: dict[str, int] = defaultdict(int)

    for node in nodes:
        attempts[node.node_id] = max(attempts[node.node_id], node.attempt)

        if node.retry_count >= t.retry_warn:
            findings.append(
                Finding(
                    code="retry_storm",
                    title=f"Node '{node.node_id}' retried {node.retry_count}x",
                    severity=Severity.HIGH if node.retry_count >= t.retry_high else Severity.MEDIUM,
                    node_id=node.node_id,
                    detail=(
                        f"The judge returned RETRY {node.retry_count} times for '{node.node_id}' "
                        f"(accepted {node.accept_count}). Every retry re-runs the loop at full token cost."
                    ),
                    suggestion=(
                        "Tighten the node's acceptance criteria, or give the worker the missing "
                        "context/tool the judge keeps asking for."
                    ),
                    metrics={"retry_count": node.retry_count, "accept_count": node.accept_count},
                )
            )

        if node.escalate_count >= t.escalate_warn:
            findings.append(
                Finding(
                    code="escalation_loop",
                    title=f"Node '{node.node_id}' escalated {node.escalate_count}x",
                    severity=Severity.HIGH,
                    node_id=node.node_id,
                    detail=(
                        f"'{node.node_id}' escalated {node.escalate_count} times — the node could not "
                        "resolve its task on its own."
                    ),
                    suggestion="Review whether this node's goal is achievable with the tools it was given.",
                    metrics={"escalate_count": node.escalate_count},
                )
            )

    for node_id, attempt in attempts.items():
        if attempt > 1:
            findings.append(
                Finding(
                    code="node_reexecuted",
                    title=f"Node '{node_id}' ran {attempt} attempts",
                    severity=Severity.MEDIUM,
                    node_id=node_id,
                    detail=f"'{node_id}' was executed {attempt} times; earlier attempts did not complete successfully.",
                    suggestion="Inspect the first attempt's error — later attempts often mask the root cause.",
                    metrics={"attempts": attempt},
                )
            )
    return findings


def detect_failures(nodes: list[NodeDetail], steps: list[NodeStepLog], t: Thresholds) -> list[Finding]:
    """Hard failures: failed nodes, bad exit statuses, and partial steps."""
    findings: list[Finding] = []

    for node in nodes:
        if not node.success:
            findings.append(
                Finding(
                    code="node_failed",
                    title=f"Node '{node.node_id}' failed",
                    severity=Severity.CRITICAL,
                    node_id=node.node_id,
                    detail=node.error or "Node reported success=False with no error message.",
                    suggestion="Start here — downstream findings are often consequences of this failure.",
                    evidence=[_short(line, 160) for line in node.stacktrace.strip().splitlines()[-3:] if line.strip()],
                    metrics={"exit_status": node.exit_status},
                )
            )
        elif node.exit_status in _BAD_EXITS:
            findings.append(
                Finding(
                    code="bad_exit_status",
                    title=f"Node '{node.node_id}' exited '{node.exit_status}'",
                    severity=_BAD_EXITS[node.exit_status],
                    node_id=node.node_id,
                    detail=(
                        f"'{node.node_id}' finished with exit status '{node.exit_status}' after "
                        f"{node.total_steps} steps."
                    ),
                    suggestion="A non-success exit usually means the loop hit its step budget or a guard.",
                    metrics={"exit_status": node.exit_status, "total_steps": node.total_steps},
                )
            )

    broken = [s for s in steps if s.error or s.is_partial]
    if broken:
        findings.append(
            Finding(
                code="step_errors",
                title=f"{len(broken)} step(s) ended in an error or partial state",
                severity=Severity.HIGH,
                detail=(
                    f"{len(broken)} step(s) recorded an exception or did not complete. Partial steps "
                    "mean the model turn was lost — its tokens were spent with no result."
                ),
                suggestion="Check for provider timeouts, context-length rejections, or tool crashes mid-turn.",
                evidence=[
                    f"{_label(s)}: {_short(s.error or 'partial step (no error recorded)')}"
                    for s in broken[: t.max_evidence]
                ],
                metrics={"broken_steps": len(broken)},
            )
        )
    return findings


def detect_context_growth(nodes: list[NodeDetail], steps: list[NodeStepLog], t: Thresholds) -> list[Finding]:
    """Nodes whose prompt kept growing until it dominated the run's cost."""
    by_node: dict[str, list[NodeStepLog]] = defaultdict(list)
    for step in steps:
        if step.input_tokens > 0:
            by_node[step.node_id].append(step)

    findings: list[Finding] = []
    for node_id, node_steps in by_node.items():
        if len(node_steps) < t.growth_min_steps:
            continue
        ordered = sorted(node_steps, key=lambda s: s.step_index)
        first, last = ordered[0].input_tokens, ordered[-1].input_tokens
        if last < t.growth_min_tokens or first <= 0 or last < first * t.growth_factor:
            continue
        findings.append(
            Finding(
                code="context_growth",
                title=f"Node '{node_id}' prompt grew {first:,} → {last:,} tokens",
                severity=Severity.MEDIUM,
                node_id=node_id,
                detail=(
                    f"Across {len(ordered)} steps the input context grew {last / first:.1f}x, ending at "
                    f"{last:,} tokens. Every later step pays for the whole accumulated history."
                ),
                suggestion=(
                    "Compact or summarise the conversation inside this node, or move bulky tool "
                    "output to files the model reads on demand."
                ),
                metrics={
                    "first_step_input_tokens": first,
                    "last_step_input_tokens": last,
                    "steps": len(ordered),
                },
            )
        )
    return findings


def detect_resend_overhead(nodes: list[NodeDetail], steps: list[NodeStepLog], t: Thresholds) -> list[Finding]:
    """Flag runs where most input tokens are re-sent conversation prefix.

    Each step of an event loop re-sends the whole conversation. Only the
    largest single send is unavoidable; the rest is prefix the provider has
    already seen and is a prime target for prompt caching or compaction.
    """
    total_input = sum(s.input_tokens for s in steps)
    if total_input < t.resend_min_total_tokens:
        return []
    largest = max((s.input_tokens for s in steps), default=0)
    overhead = total_input - largest
    ratio = overhead / total_input if total_input else 0.0
    if ratio < t.resend_ratio:
        return []
    return [
        Finding(
            code="resend_overhead",
            title=f"{ratio:.0%} of input tokens are re-sent context ({overhead:,} tokens)",
            severity=Severity.MEDIUM,
            detail=(
                f"Of {total_input:,} input tokens, roughly {overhead:,} are conversation prefix "
                "re-sent on later steps rather than new information."
            ),
            suggestion=(
                "Enable prompt caching for this provider, or shorten the loop so fewer steps carry the full history."
            ),
            metrics={
                "total_input_tokens": total_input,
                "resend_overhead_tokens": overhead,
                "ratio": round(ratio, 4),
            },
        )
    ]


def detect_slow_tools(nodes: list[NodeDetail], steps: list[NodeStepLog], t: Thresholds) -> list[Finding]:
    """Individual tool calls slow enough to dominate wall-clock time."""
    slow = [(step, call) for step in steps for call in step.tool_calls if call.duration_s >= t.slow_tool_s]
    if not slow:
        return []
    slow.sort(key=lambda pair: pair[1].duration_s, reverse=True)
    worst = slow[0][1].duration_s
    total = sum(call.duration_s for _, call in slow)
    return [
        Finding(
            code="slow_tools",
            title=f"{len(slow)} tool call(s) took over {t.slow_tool_s:.0f}s ({total:.0f}s total)",
            severity=Severity.HIGH if worst >= t.slow_tool_high_s else Severity.MEDIUM,
            detail=(
                f"The slowest tool call took {worst:.1f}s. Slow tools block the node's loop and "
                "push runs toward timeouts."
            ),
            suggestion="Add pagination/limits to these calls, or move them behind a background job.",
            evidence=[
                f"{call.duration_s:6.1f}s  {call.tool_name}  ({_label(step)})" for step, call in slow[: t.max_evidence]
            ],
            metrics={"slow_calls": len(slow), "slowest_s": round(worst, 2), "total_s": round(total, 2)},
        )
    ]


def detect_oversized_results(nodes: list[NodeDetail], steps: list[NodeStepLog], t: Thresholds) -> list[Finding]:
    """Tool results large enough to crowd out the rest of the context window."""
    big = [(step, call) for step in steps for call in step.tool_calls if len(call.result) >= t.big_result_chars]
    if not big:
        return []
    big.sort(key=lambda pair: len(pair[1].result), reverse=True)
    total_chars = sum(len(call.result) for _, call in big)
    return [
        Finding(
            code="oversized_tool_result",
            title=f"{len(big)} tool result(s) over {t.big_result_chars // 1000}k characters",
            severity=Severity.MEDIUM,
            detail=(
                f"These results add roughly {total_chars // 4:,} tokens to the conversation and are "
                "re-sent on every subsequent step of the node."
            ),
            suggestion=(
                "Truncate or summarise at the tool boundary, or write the payload to a file and hand the model a path."
            ),
            evidence=[
                f"{len(call.result) // 1000:5d}k chars  {call.tool_name}  ({_label(step)})"
                for step, call in big[: t.max_evidence]
            ],
            metrics={"oversized_results": len(big), "total_chars": total_chars},
        )
    ]


def detect_repeated_output(nodes: list[NodeDetail], steps: list[NodeStepLog], t: Thresholds) -> list[Finding]:
    """Consecutive steps where the model emitted the same text — a stuck loop."""
    by_node: dict[str, list[NodeStepLog]] = defaultdict(list)
    for step in steps:
        if step.llm_text.strip():
            by_node[step.node_id].append(step)

    findings: list[Finding] = []
    for node_id, node_steps in by_node.items():
        ordered = sorted(node_steps, key=lambda s: s.step_index)
        run_text = ""
        run_len = 0
        run_start = 0
        # Walk once, tracking the current streak of identical assistant turns.
        for step in ordered + [None]:  # sentinel flushes the final streak
            text = " ".join(step.llm_text.split()) if step is not None else None
            if text is not None and text == run_text:
                run_len += 1
                continue
            if run_len >= t.repeat_min:
                findings.append(
                    Finding(
                        code="repeated_output",
                        title=f"Node '{node_id}' produced identical output {run_len}x in a row",
                        severity=Severity.HIGH,
                        node_id=node_id,
                        detail=(
                            f"Steps {run_start}–{run_start + run_len - 1} of '{node_id}' emitted the same "
                            "assistant text. The loop is not making progress."
                        ),
                        suggestion=(
                            "The model is likely missing a tool or a piece of state it needs; check the "
                            "last tool result before the streak began."
                        ),
                        evidence=[_short(run_text, 160)],
                        metrics={"repeats": run_len, "first_step": run_start},
                    )
                )
            if step is None:
                break
            run_text, run_len, run_start = text, 1, step.step_index
    return findings


DetectorFn = Callable[[list[NodeDetail], list[NodeStepLog], Thresholds], list[Finding]]

DETECTORS: tuple[DetectorFn, ...] = (
    detect_failures,
    detect_retry_storms,
    detect_tool_thrash,
    detect_repeated_output,
    detect_failing_tools,
    detect_slow_tools,
    detect_oversized_results,
    detect_context_growth,
    detect_resend_overhead,
)
