"""
Tab health classification — pure rules over a raw extension snapshot.

The extension owns observation (``tab.audit`` returns a flat snapshot of
frame URLs, the tab's main URL, incognito flag, file-scheme access). This
module owns interpretation: each rule is a pure function that turns a
snapshot — and optionally an error string from a recent CDP call — into a
``Blocker`` describing why automation may be impaired on this tab.

Why split observation from policy: the extension lives behind the Chrome
Web Store review queue and should stay stable. Heuristics evolve weekly
as new conflicting extensions surface; they belong here, where they ship
with the runtime and are unit-testable in isolation.

Adding a new rule is one ``@register`` function. ``classify()`` walks the
registry in priority order and returns the first match.
"""

from __future__ import annotations

import re
from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Any
from urllib.parse import urlparse


@dataclass
class Blocker:
    """Structured reason why a tab can't be automated.

    Designed to flow unchanged from this module → bridge ``/contexts`` →
    side-panel UI → agent tool errors. The ``kind`` is the stable
    machine-readable id callers branch on; the ``title``/``detail``/``fix``
    strings are the human-readable surface and may evolve.
    """

    kind: str
    severity: str  # "block" — automation will fail. "warn" — degraded but usable.
    title: str
    detail: str
    fix: str
    priority: int = 100
    context: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict:
        """Serialize for the wire (agent tool response, side panel JSON).

        Drops ``priority`` — internal ordering hint, never consumed by
        callers — to keep the response slim. The full dataclass remains
        available in-process for ranking and dedup logic.
        """
        return {
            "kind": self.kind,
            "severity": self.severity,
            "title": self.title,
            "detail": self.detail,
            "fix": self.fix,
            "context": self.context,
        }


# Rule signature: (snapshot, error_or_None, ctx) -> Optional[Blocker]
Rule = Callable[[dict, "str | None", dict], "Blocker | None"]

# Registry sorted by ascending priority; first match wins.
_RULES: list[tuple[int, str, Rule]] = []


def register(*, priority: int, kind: str) -> Callable[[Rule], Rule]:
    """Decorator: add a rule to the registry.

    Lower ``priority`` values match first. ``kind`` is stored for debug
    introspection — the rule function is free to emit Blockers with a
    different kind (e.g. error-only rules sharing the snapshot rule's kind
    so duplicates fold).
    """

    def deco(fn: Rule) -> Rule:
        _RULES.append((priority, kind, fn))
        _RULES.sort(key=lambda x: x[0])
        return fn

    return deco


def classify(
    snapshot: dict | None,
    error: str | None = None,
    *,
    ctx: dict | None = None,
) -> Blocker | None:
    """Return the highest-priority matching Blocker, or None.

    Safe to call with any combination of inputs:
    - snapshot only (proactive audit after cdp.attach)
    - error only   (reactive — snapshot empty/unavailable)
    - both         (reactive — re-using the cached attach-time snapshot)
    """
    snap = snapshot or {}
    c = ctx or {}
    for _, _, rule in _RULES:
        try:
            blocker = rule(snap, error, c)
        except Exception:
            # A buggy rule must never break health reporting.
            continue
        if blocker is not None:
            return blocker
    return None


def classify_all(snapshot: dict | None, error: str | None = None, *, ctx: dict | None = None) -> list[Blocker]:
    """Like classify(), but returns every matching rule (still priority-sorted).

    Mainly useful for debugging — the UI surface uses ``classify`` to avoid
    overwhelming the user with redundant rows. Folding by ``kind`` here so a
    snapshot rule + an error-only rule with the same kind don't double up.
    """
    snap = snapshot or {}
    c = ctx or {}
    seen: set[str] = set()
    out: list[Blocker] = []
    for _, _, rule in _RULES:
        try:
            blocker = rule(snap, error, c)
        except Exception:
            continue
        if blocker is not None and blocker.kind not in seen:
            seen.add(blocker.kind)
            out.append(blocker)
    return out


# ───────────────────────────────────────────────────────────────────────────
# Snapshot helpers
# ───────────────────────────────────────────────────────────────────────────

_CHROME_EXT_PATH_RE = re.compile(r"^chrome-extension://([a-z0-9]+)/")


def _extension_id_from_url(url: str) -> str | None:
    m = _CHROME_EXT_PATH_RE.match(url or "")
    return m.group(1) if m else None


# Known offenders we name explicitly so the side panel + agent errors can say
# "Blocked by Calendly" instead of "Blocked by extension cbhilkc…". Add ids
# here as we encounter them in the wild; an unknown id falls through to the
# generic "Another extension" wording.
#
# We deliberately do NOT list per-site disable affordances ("click the
# toolbar icon → Disable on this site") — they vary between extensions and
# are easy to get wrong; the user discovered this when our Calendly hint
# referenced a UI element that doesn't exist. Uniform guidance ("disable
# the extension in chrome://extensions, then reload") is correct for every
# offender even if it's a click more than the optimal path.
KNOWN_EXTENSIONS: dict[str, dict[str, str]] = {
    "cbhilkcodigmigfbnphipnnmamjfkipp": {"name": "Calendly"},
    "kbfnbcaeplbcioakkpcpgfkobkghlhen": {"name": "Grammarly"},
    "hdokiejnpimakedhajhdlcegeplioahd": {"name": "LastPass"},
    "aeblfdkhhhdcdjpifhhbdiojplfjncoa": {"name": "1Password"},
    "cjpalhdlnbpafiamejdnhcphjbkeiagm": {"name": "uBlock Origin"},
    "gighmmpiobklfepjocnamgkkbiglidom": {"name": "AdBlock"},
    "cfhdojbkjhnklbpkdaibdccddilifddb": {"name": "Adblock Plus"},
    "bmnlcjabgnpnenekpadlanbbkooimhnj": {"name": "Honey"},
    "mlomiejdfkolichcflejclcbmpeaniij": {"name": "Ghostery"},
    # Chrome's bundled PDF viewer is itself an extension; surfaces here
    # for PDF tabs. The "fix" then is just "navigate away from the PDF".
    "nmmhkkegccagdldgiimedpiccmgmieda": {"name": "Chrome PDF Viewer"},
}


def lookup_extension(ext_id: str) -> dict[str, str | bool]:
    """Return ``{name, known}`` for an extension id.

    ``known=True`` when ``ext_id`` is in ``KNOWN_EXTENSIONS`` and the
    name is the real one ("Calendly"). ``known=False`` for ids we
    don't recognise — callers use this flag to pick "Blocked by
    Calendly" vs "Blocked by an unknown extension" wording.
    """
    info = KNOWN_EXTENSIONS.get(ext_id)
    if info is not None:
        return {"name": info["name"], "known": True}
    return {"name": "an unknown extension", "known": False}


def _chrome_web_store_url(ext_id: str) -> str:
    """Public listing page for the extension; users can click through to
    see what it is when the id alone isn't enough."""
    return f"https://chromewebstore.google.com/detail/{ext_id}"


def _iter_frame_urls(snapshot: dict):
    """Yield (url, declared_extension_id_or_None) over every observable frame.

    Three sources, each with different blind spots:

    * ``domFrames`` (page-DOM probe via chrome.scripting.executeScript with
      a static func that runs ``document.querySelectorAll('iframe, frame')``
      in MAIN world). The ONLY source that sees foreign-extension iframes
      on tabs where the other APIs scrub them — verified empirically on
      LinkedIn + Calendly 2026-05-27. iframe.src exposes the chrome-
      extension://<id>/... URL directly.
    * ``targets`` (chrome.debugger.getTargets) — Chrome filters foreign-
      extension iframe targets here for security; sees our own extension's
      frames but never the offender's. Kept for the legacy classification
      path on non-foreign-frame tabs (DevTools attached, enterprise policy).
    * ``cdpFrames`` (Page.getFrameTree via CDP) — sees in-process iframes
      when CDP works, but Page.getFrameTree itself fails on foreign-frame-
      blocked tabs.

    Each yield is ``(url, declared_extension_id_or_None)``; the
    classifier extracts the id from the url when ``declared`` is None.

    Note: chrome.webNavigation.getAllFrames was tried as a fourth source
    but Chrome scrubs foreign-extension OOPIFs from it the same way as
    chrome.debugger.getTargets, so it added nothing the snapshot rule
    couldn't get from ``domFrames``. Removed 2026-05-27 along with the
    ``webNavigation`` permission.
    """
    for f in snapshot.get("domFrames") or []:
        yield f.get("src") or "", None
    for t in snapshot.get("targets") or []:
        yield t.get("url") or "", t.get("extensionId")
    for f in snapshot.get("cdpFrames") or []:
        yield f.get("url") or "", None


# ───────────────────────────────────────────────────────────────────────────
# Rules
# ───────────────────────────────────────────────────────────────────────────

# Privileged Chrome surfaces — chrome.debugger.attach is denied outright.
# Cheapest possible check; runs first so we never bother probing further.
_PRIVILEGED_PREFIXES = (
    "chrome://",
    "chrome-untrusted://",
    "devtools://",
    "view-source:",
    "chrome-search://",
    "chrome-error://",
)


@register(priority=10, kind="privileged_scheme")
def _privileged_scheme(snap: dict, err: str | None, ctx: dict) -> Blocker | None:
    url = snap.get("url") or ""
    # The new-tab page is a privileged URL but it's transient — the user is
    # about to type or click their way off it. Flagging it produces a noisy
    # "Privileged Chrome page" banner that sticks around after navigation
    # (cached blockers aren't invalidated on user-driven nav of tabs we
    # haven't CDP-attached to), so just skip evaluation here. Chrome reports
    # the new-tab URL under a handful of aliases depending on version and
    # profile state (chrome://newtab/, chrome://new-tab-page/, the legacy
    # chrome-search://local-ntp/…), so match all of them.
    if url.startswith("chrome://newtab") or url.startswith("chrome://new-tab-page") or url.startswith("chrome-search://local-ntp"):
        return None
    for prefix in _PRIVILEGED_PREFIXES:
        if url.startswith(prefix):
            scheme = prefix.rstrip(":/")
            return Blocker(
                kind="privileged_scheme",
                severity="block",
                title="Privileged Chrome page",
                detail=(f"This tab is on {scheme}, which Chrome forbids extensions from automating."),
                fix="Navigate to a regular http(s) page or open a new tab.",
                priority=10,
                context={"url": url, "scheme": scheme},
            )
    return None


# Chrome Web Store has an explicit carve-out — extensions cannot debug it.
# (Otherwise an extension could auto-uninstall its rivals.)
_WEB_STORE_HOSTS = ("chrome.google.com", "chromewebstore.google.com")


@register(priority=15, kind="chrome_web_store")
def _chrome_web_store(snap: dict, err: str | None, ctx: dict) -> Blocker | None:
    url = snap.get("url") or ""
    try:
        parsed = urlparse(url)
    except Exception:
        return None
    host = (parsed.hostname or "").lower()
    if host == "chromewebstore.google.com" or (host == "chrome.google.com" and parsed.path.startswith("/webstore")):
        return Blocker(
            kind="chrome_web_store",
            severity="block",
            title="Chrome Web Store",
            detail="Chrome hard-codes a refusal to let any extension automate the Web Store.",
            fix="Navigate to a different site.",
            priority=15,
            context={"url": url},
        )
    return None


# Foreign-extension iframe (the Calendly case). Detected from the snapshot.
# Chrome's PDF viewer also surfaces here — it's an internal extension — but
# the user-actionable advice is the same: there's another extension's frame
# in this tab, and Chrome won't let our debugger touch it.
def _foreign_extension_blocker(
    *,
    foreign_ids: list[str],
    site_url: str | None,
    priority: int,
    matched_from_snapshot: bool,
) -> Blocker:
    """Build the Blocker for a foreign-extension-frame hit.

    Single-sentence ``detail`` + single-sentence ``fix``, no repetition
    of the offender name across fields. Same wording shape whether the
    offender is in ``KNOWN_EXTENSIONS`` ("Calendly") or unknown ("an
    unknown extension") — only the noun changes. The chrome web store
    URL is inlined so the user can click through to identify an
    unknown extension without first opening chrome://extensions.
    """
    first = foreign_ids[0]
    info = lookup_extension(first)
    name: str = info["name"]  # "Calendly" or "an unknown extension"
    is_known: bool = bool(info.get("known"))
    store_url = _chrome_web_store_url(first)
    extensions_url = f"chrome://extensions/?id={first}"
    extra_count = f" (+{len(foreign_ids) - 1} more)" if len(foreign_ids) > 1 else ""

    # Capitalised subject for sentence-start (detail), bare name for the
    # title and the fix's mid-sentence reference. "an unknown extension"
    # capitalises naturally to "An unknown extension"; "Calendly" stays
    # "Calendly".
    subject_start = name[0].upper() + name[1:] if name else name

    title = f"Blocked by {name}"
    detail = f"{subject_start} ({store_url}) injected a frame into this tab{extra_count}, which prevents Hive from automating the page."
    fix = f"Open {extensions_url}, turn it off, and reload this tab."
    # Agent instruction. Only the policy bits the LLM can't infer from
    # title/detail/fix: don't auto-navigate the user's tab (chrome://extensions
    # is a context switch); ask first, then use ``browser_open`` if they agree
    # (it's been patched to accept chrome:// URLs).
    agent_action = "Surface the blocker, then ask before opening chrome://extensions — call browser_open with the fix URL only if the user agrees."
    return Blocker(
        kind="foreign_extension_frame",
        severity="block",
        title=title,
        detail=detail,
        fix=fix,
        priority=priority,
        # Only the fields a consumer actually reads. The side panel uses
        # offender_extension_id (for the chrome://extensions deep link)
        # and offender_known (to format the button label "Open Calendly
        # in chrome://extensions" vs the unknown-id case). offender_name
        # is convenient enough to keep even though it duplicates the
        # title — labels and headers can drift. ``agent_action`` is the
        # LLM-facing instruction; the side panel ignores it.
        context={
            "offender_extension_id": first,
            "offender_name": name,
            "offender_known": is_known,
            "agent_action": agent_action,
        },
    )


@register(priority=20, kind="foreign_extension_frame")
def _foreign_extension_frame(snap: dict, err: str | None, ctx: dict) -> Blocker | None:
    own = snap.get("ourExtensionId") or ctx.get("our_extension_id")
    if not own:
        return None
    foreign: set[str] = set()
    for url, declared in _iter_frame_urls(snap):
        ext_id = declared or _extension_id_from_url(url)
        if ext_id and ext_id != own:
            foreign.add(ext_id)
    if not foreign:
        return None
    return _foreign_extension_blocker(
        foreign_ids=sorted(foreign),
        site_url=snap.get("url"),
        priority=20,
        matched_from_snapshot=True,
    )


# Same condition as above, but matched off the CDP error string when the
# snapshot is unavailable or stale (Calendly's MutationObserver re-injects
# after attach-time audit). Same kind → folded by classify_all.
@register(priority=21, kind="foreign_extension_frame")
def _foreign_extension_frame_from_error(snap: dict, err: str | None, ctx: dict) -> Blocker | None:
    if not err:
        return None
    e = err.lower()
    if "chrome-extension://" not in e or "different extension" not in e:
        return None
    # The CDP error string doesn't include the offender id (Chrome scrubs it
    # to avoid leaking other extensions' identities). Reuse whatever ids the
    # cached snapshot saw — usually populated by the proactive attach-time
    # audit. If we genuinely have nothing, fall back to a generic message.
    own = snap.get("ourExtensionId") or ctx.get("our_extension_id")
    foreign: list[str] = []
    if own:
        seen: set[str] = set()
        for url, declared in _iter_frame_urls(snap):
            ext_id = declared or _extension_id_from_url(url)
            if ext_id and ext_id != own and ext_id not in seen:
                seen.add(ext_id)
                foreign.append(ext_id)
    if foreign:
        return _foreign_extension_blocker(
            foreign_ids=foreign,
            site_url=snap.get("url"),
            priority=21,
            matched_from_snapshot=False,
        )
    return Blocker(
        kind="foreign_extension_frame",
        severity="block",
        title="Blocked by another extension",
        detail=(
            "Chrome refused a debugger command because another extension's "
            "iframe is in this tab, but Hive hasn't been able to identify "
            "which one yet. The extension may have re-injected after attach."
        ),
        fix=(
            "Open chrome://extensions and disable extensions that overlay "
            "content on this site (common culprits: Calendly, Grammarly, "
            "ad-blockers, password managers), then retry."
        ),
        priority=21,
        context={"matched_from": "error_no_snapshot"},
    )


# A second human DevTools window is attached — only one debugger client allowed.
@register(priority=30, kind="devtools_attached")
def _devtools_attached(snap: dict, err: str | None, ctx: dict) -> Blocker | None:
    if not err:
        return None
    e = err.lower()
    # Chromium phrasings observed in the wild.
    hit = ("another debugger" in e) or ("debugger is already attached" in e) or ("cannot attach" in e and "devtools" in e)
    if not hit:
        return None
    return Blocker(
        kind="devtools_attached",
        severity="block",
        title="DevTools is open on this tab",
        detail="Only one debugger client per tab is allowed; a human DevTools window is holding it.",
        fix="Close DevTools on the target tab.",
        priority=30,
    )


# Managed Chrome can ship policies that disable the debugger API.
@register(priority=40, kind="enterprise_policy")
def _enterprise_policy(snap: dict, err: str | None, ctx: dict) -> Blocker | None:
    if not err:
        return None
    e = err.lower()
    if "policy" in e and ("debug" in e or "remote" in e):
        return Blocker(
            kind="enterprise_policy",
            severity="block",
            title="Blocked by Chrome policy",
            detail="A Chrome enterprise policy disabled the debugger API on this device.",
            fix="Contact your IT admin — RemoteDebuggingAllowed must be enabled.",
            priority=40,
        )
    return None


# file:// URLs need the extension's "Allow access to file URLs" toggle on.
@register(priority=50, kind="file_access_denied")
def _file_access_denied(snap: dict, err: str | None, ctx: dict) -> Blocker | None:
    url = snap.get("url") or ""
    if not url.startswith("file://"):
        return None
    if snap.get("fileAccess") is True:
        return None
    return Blocker(
        kind="file_access_denied",
        severity="block",
        title="File access not allowed",
        detail="The Hive extension isn't permitted to operate on file:// URLs.",
        fix=('Open chrome://extensions, find Hive Browser Bridge → Details, and enable "Allow access to file URLs".'),
        priority=50,
    )


__all__ = ["Blocker", "KNOWN_EXTENSIONS", "Rule", "classify", "classify_all", "lookup_extension", "register"]
