"""Guardrail invariants for the measured tool-tiering keep-sets.

These lock in the 2026-07 tool-cost analysis so a future category edit can't
silently re-bloat the eager tier. Byte-level budgets need live MCP schemas
(sizes live in the servers, not in this repo), so the enforcement here is
structural: category partitions, keep-set membership, and the measured-cold
tail staying out of the eager tiers.
"""

from framework.agents.queen.queen_tools_defaults import (
    _TOOL_CATEGORIES,
    ALWAYS_ENABLED_CATEGORIES,
    WORKER_ALWAYS_ENABLED_CATEGORIES,
    always_enabled_tool_names,
    worker_always_enabled_tool_names,
)

# Tools measured at ~0 invocations per 1k carries in prod (2026-07 datalog
# sampling) that used to ride every request. If one of these shows up eager
# again, either the measurement was redone (update this list with the new
# data) or someone re-bloated the tier by accident (fix the category).
MEASURED_COLD = {
    "browser_upload",
    "browser_dialog_respond",
    "browser_console",
    "browser_html",
    "browser_get_text",
    "browser_select",
    "browser_resize",
    "search_messages",
    "terminal_rg",
    "terminal_glob",
    "pdf_read",
}

# Ceiling on the worker keep-set size (concrete tool names). The measured
# eager core is 18 names; headroom to 24 before this trips. Growing past
# that deserves a deliberate decision, not a drive-by category edit.
WORKER_KEEP_SET_MAX = 24


def test_browser_split_partitions_legacy_categories():
    core = set(_TOOL_CATEGORIES["browser_core"])
    extended = set(_TOOL_CATEGORIES["browser_extended"])
    legacy = set(_TOOL_CATEGORIES["browser_basic"]) | set(_TOOL_CATEGORIES["browser_interaction"])
    # browser_setup is a shared anchor present in every browser category (it
    # pre-activates the browser-automation skill), so core/extended overlap
    # only on it; otherwise they partition the legacy set.
    assert core & extended == {"browser_setup"}
    assert core | extended == legacy


def test_terminal_split_partitions_basic():
    core = set(_TOOL_CATEGORIES["terminal_core"])
    extended = set(_TOOL_CATEGORIES["terminal_extended"])
    basic = set(_TOOL_CATEGORIES["terminal_basic"])
    assert core & extended == set()
    assert core | extended == basic


def test_keep_set_categories_exist():
    for cat in WORKER_ALWAYS_ENABLED_CATEGORIES | ALWAYS_ENABLED_CATEGORIES:
        assert cat in _TOOL_CATEGORIES, f"unknown category in a keep-set: {cat}"


def test_worker_keep_set_excludes_measured_cold_tail():
    eager = worker_always_enabled_tool_names()
    assert eager, "worker keep-set unexpectedly empty (split accidentally dark?)"
    overlap = eager & MEASURED_COLD
    assert not overlap, f"measured-cold tools re-entered the worker eager tier: {sorted(overlap)}"


def test_queen_eager_tier_excludes_browser_cold_tail():
    eager = always_enabled_tool_names()
    browser_cold = {n for n in MEASURED_COLD if n.startswith("browser_")}
    overlap = eager & browser_cold
    assert not overlap, f"cold browser tools re-entered the queen eager tier: {sorted(overlap)}"


def test_worker_keep_set_size_budget():
    eager = worker_always_enabled_tool_names()
    assert len(eager) <= WORKER_KEEP_SET_MAX, f"worker keep-set grew to {len(eager)} names (max {WORKER_KEEP_SET_MAX}): {sorted(eager)}"


def test_worker_keep_set_keeps_the_measured_hot_core():
    eager = worker_always_enabled_tool_names()
    # The tools that do the actual work (all ≥5 invocations/1k carries).
    # browser_setup is the eager anchor (browser_interact/script are now
    # searchable/gated rather than always-on).
    assert {"browser_setup", "terminal_exec", "attach_file", "web_scrape"} <= eager
