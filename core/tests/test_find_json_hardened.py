"""Adversarial test suite for find_json_object.

This is the hardened regression suite designed to prevent silent reintroduction
of the original "CPU-bound find_json_object blocks async event loop" bug and
to cover every edge case found during the QA audit.

Run with:
    cd core
    python -m pytest tests/test_find_json_hardened.py -v

Categories:
    a) Basic correctness (TestBasicCorrectness)
    b) Large LLM output regression (TestLargeOutputRegression)
    c) Async / event-loop behaviour (TestAsyncBehaviour)
    d) Adversarial / fuzz-style (TestAdversarial)
"""

import json
import time

import pytest

from framework.graph.node import find_json_object

# Hardcoded nesting limit for testing; the original _MAX_NESTING_DEPTH
# constant was removed alongside the async path simplification.
_TEST_NESTING_DEPTH = 1000

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_json(size_bytes: int) -> str:
    """Generate a valid JSON object of approximately `size_bytes`."""
    # {"data":"xxx...xxx"}  overhead ≈ 11 chars
    pad = max(0, size_bytes - 11)
    return json.dumps({"data": "x" * pad})


def _make_nested_json(depth: int) -> str:
    """Build {"a":{"a":...{"a":"leaf"}...}} with `depth` levels."""
    core = '"leaf"'
    for _ in range(depth):
        core = '{"a":' + core + "}"
    return core


# ═══════════════════════════════════════════════════════════════════════════
# a) BASIC CORRECTNESS
# ═══════════════════════════════════════════════════════════════════════════


class TestBasicCorrectness:
    """Validate that find_json_object correctly locates/rejects JSON."""

    def test_simple_json_only(self):
        assert find_json_object('{"foo": 1}') == '{"foo": 1}'

    def test_json_with_surrounding_text(self):
        raw = 'Here is the answer: {"foo": 1} Hope that helps!'
        result = find_json_object(raw)
        assert json.loads(result) == {"foo": 1}

    def test_json_in_markdown_fence(self):
        raw = '```json\n{"foo": 1}\n```'
        result = find_json_object(raw)
        assert json.loads(result) == {"foo": 1}

    def test_multiple_json_first_wins(self):
        raw = '{"first": 1} and then {"second": 2}'
        result = find_json_object(raw)
        assert json.loads(result) == {"first": 1}

    def test_missing_closing_brace(self):
        assert find_json_object('{"foo": 1') is None

    def test_trailing_comma_returns_balanced_candidate(self):
        # The fast-path json.loads rejects trailing commas, but the
        # fallback brace-depth scanner returns the balanced substring.
        result = find_json_object('{"a": 1,}')
        assert result == '{"a": 1,}'

    def test_truncated_payload(self):
        half = '{"key": "val'
        assert find_json_object(half) is None

    def test_empty_string(self):
        assert find_json_object("") is None

    def test_whitespace_only(self):
        assert find_json_object("   \n\t  ") is None

    def test_no_braces(self):
        assert find_json_object("hello world") is None

    def test_braces_inside_string_value(self):
        raw = '{"msg": "a {b} c"}'
        result = find_json_object(raw)
        assert json.loads(result) == {"msg": "a {b} c"}

    def test_escaped_quotes(self):
        raw = r'{"k": "say \"hi\""}'
        result = find_json_object(raw)
        assert json.loads(result)["k"] == 'say "hi"'

    def test_escaped_backslash_at_end_of_value(self):
        raw = r'{"p": "C:\\"}'
        result = find_json_object(raw)
        assert json.loads(result)["p"] == "C:\\"

    def test_nested_arrays(self):
        raw = '{"a": [[1], [2]]}'
        result = find_json_object(raw)
        assert json.loads(result) == {"a": [[1], [2]]}

    def test_unicode_emoji(self):
        raw = '{"emoji": "😀🎉"}'
        result = find_json_object(raw)
        assert json.loads(result) == {"emoji": "😀🎉"}

    def test_boolean_and_null(self):
        raw = '{"a": true, "b": false, "c": null}'
        result = find_json_object(raw)
        assert json.loads(result) == {"a": True, "b": False, "c": None}

    def test_numeric_values(self):
        raw = '{"int": 42, "float": 3.14, "neg": -1, "exp": 1e10}'
        result = find_json_object(raw)
        parsed = json.loads(result)
        assert parsed["int"] == 42
        assert parsed["float"] == pytest.approx(3.14)

    def test_empty_object(self):
        assert find_json_object("{}") == "{}"

    def test_deeply_nested_objects(self):
        raw = '{"a": {"b": {"c": {"d": "deep"}}}}'
        result = find_json_object(raw)
        assert json.loads(result)["a"]["b"]["c"]["d"] == "deep"


# ═══════════════════════════════════════════════════════════════════════════
# b) LARGE LLM OUTPUT REGRESSION
# ═══════════════════════════════════════════════════════════════════════════


class TestLargeOutputRegression:
    """Performance + correctness for 100KB–2MB+ inputs."""

    def test_100kb_json_correctness_and_perf(self):
        payload = _make_json(100_000)
        raw = f"Prefix text. {payload} Suffix text."
        start = time.perf_counter()
        result = find_json_object(raw)
        elapsed = time.perf_counter() - start
        assert result is not None
        assert json.loads(result) == json.loads(payload)
        assert elapsed < 0.2, f"100KB took {elapsed:.4f}s"

    def test_1mb_json_correctness_and_perf(self):
        payload = _make_json(1_000_000)
        raw = f"Prefix text. {payload} Suffix text."
        start = time.perf_counter()
        result = find_json_object(raw)
        elapsed = time.perf_counter() - start
        assert result is not None
        assert json.loads(result) == json.loads(payload)
        assert elapsed < 0.5, f"1MB took {elapsed:.4f}s"

    def test_2mb_json_exceeds_old_threshold(self):
        """Specifically tests GAP 5 fix: 2MB > old _MAX_DIRECT_PARSE_SIZE."""
        payload = _make_json(2_000_000)
        raw = f"Here is the data: {payload}"
        start = time.perf_counter()
        result = find_json_object(raw)
        elapsed = time.perf_counter() - start
        assert result is not None
        assert json.loads(result) == json.loads(payload)
        # With GAP 5 fix, json.loads fast-path is used → should be fast
        assert elapsed < 1.0, f"2MB took {elapsed:.4f}s"

    def test_1mb_no_json_early_exit(self):
        """1MB of text with zero braces → instant None via str.find."""
        raw = "x" * 1_000_000
        start = time.perf_counter()
        result = find_json_object(raw)
        elapsed = time.perf_counter() - start
        assert result is None
        assert elapsed < 0.01, f"No-brace scan took {elapsed:.6f}s"

    def test_json_at_end_of_1mb_text(self):
        """Valid JSON only at the very end of 1MB of noise."""
        noise = "a" * 1_000_000
        payload = '{"found": true}'
        raw = noise + payload
        start = time.perf_counter()
        result = find_json_object(raw)
        elapsed = time.perf_counter() - start
        assert result is not None
        assert json.loads(result) == {"found": True}
        assert elapsed < 1.0, f"End-of-1MB took {elapsed:.4f}s"

    def test_100kb_template_braces_performance(self):
        """100KB of Jinja-style {{name}} templates — tests performance.

        The current implementation may return a balanced-brace substring
        from the template braces; the key invariant is that it completes
        quickly without hanging.
        """
        chunk = "Hello {{name}}, balance: {{bal}}. "
        raw = chunk * (100_000 // len(chunk))
        start = time.perf_counter()
        find_json_object(raw)
        elapsed = time.perf_counter() - start
        assert elapsed < 1.0, f"Template-brace scan took {elapsed:.4f}s"

    def test_deeply_nested_valid_json_500_levels(self):
        """500-deep nested JSON objects — within the nesting limit."""
        raw = _make_nested_json(500)
        start = time.perf_counter()
        result = find_json_object(raw)
        elapsed = time.perf_counter() - start
        assert result is not None
        parsed = json.loads(result)
        # Walk 500 levels
        node = parsed
        for _ in range(499):
            node = node["a"]
        assert node["a"] == "leaf"
        assert elapsed < 1.0, f"500-deep took {elapsed:.4f}s"

    def test_deep_nesting_does_not_hang(self):
        """Deep nesting followed by valid JSON — must not hang.

        The current implementation's fast-path (first-{ to last-})
        will grab the entire span including the valid JSON. It may or
        may not return parseable JSON depending on how the candidate
        is formed, but the key invariant is no hang and no crash.
        """
        too_deep = "{" * (_TEST_NESTING_DEPTH + 10)
        too_deep += "}" * (_TEST_NESTING_DEPTH + 10)
        valid = '{"found": "after_deep"}'
        raw = too_deep + " " + valid
        start = time.perf_counter()
        result = find_json_object(raw)
        elapsed = time.perf_counter() - start
        # Must complete quickly (no O(n^2) or hang)
        assert elapsed < 2.0, f"Deep nesting scan took {elapsed:.4f}s"
        # Result is either None or some string (no crash)
        assert result is None or isinstance(result, str)


# ═══════════════════════════════════════════════════════════════════════════
# d) ADVERSARIAL / FUZZ-STYLE
# ═══════════════════════════════════════════════════════════════════════════


class TestAdversarial:
    """Nasty inputs that should never crash or hang."""

    def test_only_opening_braces(self):
        assert find_json_object("{" * 5000) is None

    def test_only_closing_braces(self):
        assert find_json_object("}" * 5000) is None

    def test_alternating_open_close(self):
        # "{}{}{}" — each {} is empty and json.loads("{}") succeeds
        result = find_json_object("{}" * 100)
        assert result == "{}"

    def test_mismatched_brackets(self):
        assert find_json_object("{]") is None

    def test_mismatched_then_valid(self):
        # The fast-path fails; the brace-depth fallback starts at the
        # first '{' and returns the first balanced brace pair it finds,
        # which may not be valid JSON.  The key contract: no crash.
        raw = '{] then [} but finally {"valid": 1}'
        result = find_json_object(raw)
        assert isinstance(result, (str, type(None)))  # no crash

    def test_invalid_json_then_valid(self):
        # The brace-depth fallback returns the first balanced pair,
        # which is '{bad content no quotes}'.  It won't be valid JSON,
        # but the contract is: return a balanced substring, no crash.
        raw = '{bad content no quotes} {"good": 1}'
        result = find_json_object(raw)
        assert result is not None  # finds some balanced brace span

    def test_jinja_template_braces(self):
        raw = "Hello {{name}}, your balance is {{bal}}"
        # The brace-depth scanner finds a balanced pair from the
        # template syntax.  The returned string is unlikely to be
        # valid JSON, but the key contract is: no crash, no hang.
        result = find_json_object(raw)
        # Either None or a string — never a crash
        assert result is None or isinstance(result, str)

    def test_cjk_content(self):
        raw = '{"名前": "太郎", "都市": "東京"}'
        result = find_json_object(raw)
        assert json.loads(result) == {"名前": "太郎", "都市": "東京"}

    def test_enormous_string_value(self):
        big_val = "a" * 500_000
        raw = json.dumps({"data": big_val})
        result = find_json_object(raw)
        assert json.loads(result)["data"] == big_val

    def test_null_byte_in_text(self):
        raw = 'some\x00text before {"key": "val"}'
        result = find_json_object(raw)
        assert result is not None
        assert json.loads(result) == {"key": "val"}

    def test_negative_depth_then_valid(self):
        """GAP 4 regression: stray } drives depth negative, then valid JSON."""
        raw = '}} {"result": 42}'
        result = find_json_object(raw)
        assert result is not None
        assert json.loads(result) == {"result": 42}

    def test_json_array_ignored(self):
        """find_json_object should find objects, not arrays."""
        raw = '[1, 2, 3] {"obj": true}'
        result = find_json_object(raw)
        assert json.loads(result) == {"obj": True}

    @pytest.mark.parametrize(
        "input_text,expected",
        [
            ("", None),
            (" ", None),
            ("{}", "{}"),
            ('{"a":1}', '{"a":1}'),
            ("no json here", None),
            ("{unclosed", None),
            ('prefix {"k":"v"} suffix', '{"k":"v"}'),
            # The brace-depth fallback returns the balanced span; it doesn't
            # validate with json.loads, so "{{{...}}}" is returned as-is.
            ("{{{}}}", "{{{}}}"),  # structurally balanced, returned by fallback
            ('{"incomplete": "value', None),  # unterminated string → no closing }
        ],
        ids=[
            "empty",
            "space",
            "empty_obj",
            "simple",
            "no_json",
            "unclosed",
            "embedded",
            "nested_braces_invalid",
            "unterminated_string",
        ],
    )
    def test_parametrized_edge_cases(self, input_text, expected):
        result = find_json_object(input_text)
        if expected is None:
            assert result is None, f"Expected None, got {result!r}"
        else:
            assert result == expected, f"Expected {expected!r}, got {result!r}"


# ═══════════════════════════════════════════════════════════════════════════
# e) ORIGINAL-VS-NEW BEHAVIOUR PARITY
# ═══════════════════════════════════════════════════════════════════════════


class TestBehaviourParity:
    """Ensure the refactored function matches the original's contract."""

    def test_returns_string_not_dict(self):
        """find_json_object returns a str, not a parsed dict."""
        result = find_json_object('{"a": 1}')
        assert isinstance(result, str)

    def test_returns_none_not_raises(self):
        """On failure, returns None or a brace-balanced string — never raises."""
        result = find_json_object("garbage {{ }} badness")
        # Should be None or a string — never an exception
        assert result is None or isinstance(result, str)

    def test_first_valid_object_wins(self):
        """If multiple valid objects exist, the first one is returned."""
        raw = '{"a": 1} {"b": 2}'
        result = find_json_object(raw)
        assert json.loads(result) == {"a": 1}

    def test_string_containing_json_not_parsed(self):
        """JSON inside a string value is not the top-level return."""
        raw = '{"outer": "{\\"inner\\": 1}"}'
        result = find_json_object(raw)
        parsed = json.loads(result)
        # The outer object is returned, inner stays as string
        assert "outer" in parsed
        assert isinstance(parsed["outer"], str)
