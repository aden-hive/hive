"""The email body is TWO fields — `html` and `text` — and both must go out right.

On 2026-07-13 a colony sent 652 outbound emails that arrived as ONE JAMMED
LINE. Nobody wrote bad markup. The bodies were stored correctly in the tracker
as plain text with `\\n` line breaks, but the tool's only body field was called
`html_content` and every provider ships it as `text/html` (Gmail `MIMEText(html,
"html")`, SendGrid `type: text/html`, Mailjet `HTMLPart`). HTML collapses
newlines into whitespace, so greeting, pitch and signature ran together.

The trap was that the send SUCCEEDED — real provider message id, `{"success":
True}`, send log `sent`. The damage was invisible from every vantage point
inside the system; only the recipient's inbox showed it. So the fix is not "tell
the agent to remember": the interface now names both versions explicitly, the
way the ESPs themselves document it, so an agent holding plain text has an
obvious right place to put it and no way to silently mangle it.

`_resolve_body` is that guarantee. If you are about to simplify it back down to
one field, you are re-arming the bug.
"""

from __future__ import annotations

import pytest

from aden_tools.tools.senders_tool.senders_tool import (
    _html_to_text,
    _resolve_body,
    _text_to_html,
)

# The exact body shape the colony stores in its tracker: paragraphs separated by
# a blank line, and a signature block whose lines are single newlines.
TRACKER_BODY = (
    "Hi Sarah,\n"
    "\n"
    "I noticed Acme is hiring 12 SDRs this quarter.\n"
    "That usually means ramp time is the bottleneck.\n"
    "\n"
    "Best,\n"
    "Chris Voss\n"
    "Head of Outbound"
)


def test_text_only_generates_html_with_real_line_breaks() -> None:
    """The 652-email bug: an agent with a plain-text body must not be able to jam it."""
    html, text = _resolve_body(html="", text=TRACKER_BODY, legacy="")

    # Single newlines become <br>, blank lines become paragraphs ...
    assert "Best,<br>Chris Voss<br>Head of Outbound" in html
    assert "this quarter.<br>That usually means" in html
    assert "<p>Hi Sarah,</p>" in html
    # ... and the regression itself: no two lines separated by bare whitespace.
    assert "Chris Voss Head of Outbound" not in html
    # The caller's plain text is sent verbatim as the text/plain alternative.
    assert text == TRACKER_BODY


def test_html_only_generates_a_readable_text_alternative() -> None:
    """The plain part is what text-only clients and spam filters read — never junk."""
    html, text = _resolve_body(
        html="<p>Hi Sarah,</p><p>We ship <strong>fast</strong>.<br>Worth a chat?</p>",
        text=None,
        legacy="",
    )
    assert html.startswith("<p>Hi Sarah,")  # untouched
    assert text == "Hi Sarah,\n\nWe ship fast.\nWorth a chat?"


def test_both_provided_are_used_verbatim() -> None:
    """When the caller wrote both versions, we derive nothing and override nothing."""
    html, text = _resolve_body(html="<p>Rich</p>", text="Plain", legacy="")
    assert (html, text) == ("<p>Rich</p>", "Plain")


def test_empty_text_opts_out_of_the_plain_part() -> None:
    """text="" is an explicit opt-out (per the ESP convention), not "derive one"."""
    html, text = _resolve_body(html="<p>HTML only</p>", text="", legacy="")
    assert html == "<p>HTML only</p>"
    assert text == ""


def test_legacy_html_content_holding_plain_text_is_still_safe() -> None:
    """Old colonies pass PLAIN TEXT into `html_content` — that WAS the bug.

    The deprecated field is sniffed, not trusted by its name, so a pinned colony
    that never migrates still sends correctly-broken email.
    """
    html, text = _resolve_body(html="", text=None, legacy=TRACKER_BODY)
    assert "Best,<br>Chris Voss<br>Head of Outbound" in html
    assert text == TRACKER_BODY


def test_legacy_html_content_holding_real_html_still_works() -> None:
    """...and a caller that genuinely passed markup keeps working unchanged."""
    html, text = _resolve_body(html="", text=None, legacy="<p>Hi</p><p>Real markup.</p>")
    assert html == "<p>Hi</p><p>Real markup.</p>"
    assert text == "Hi\n\nReal markup."


def test_special_characters_are_escaped_not_broken() -> None:
    """Plain text is escaped into HTML — an unescaped '<' would corrupt the markup."""
    html, _ = _resolve_body(html="", text="R&D team <3\nTerms & conditions", legacy="")
    assert "R&amp;D team &lt;3" in html
    assert "Terms &amp; conditions" in html


def test_html_to_text_unescapes_entities() -> None:
    """Round-tripping must not leave &amp; in the body a human reads."""
    assert _html_to_text("<p>R&amp;D team &lt;3</p>") == "R&D team <3"


@pytest.mark.parametrize("body", ["", "   ", "\n\n"])
def test_empty_bodies_do_not_become_markup(body: str) -> None:
    """An empty body is rejected by the tool; it must not become <p></p> here."""
    assert _text_to_html(body).strip() == ""


def test_no_body_at_all_resolves_to_nothing() -> None:
    """Nothing in, nothing out — the tool turns this into a caller-facing error."""
    assert _resolve_body(html="", text=None, legacy="") == ("", "")
