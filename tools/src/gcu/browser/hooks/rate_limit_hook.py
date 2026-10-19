"""Script hook: social-media rate limiting with auto identity detection.

Reads ``RATE_LIMITED_ACTIONS`` (list) or ``RATE_LIMITED_ACTION`` (single
dict) from the script module.  If present, auto-detects the logged-in
account from the current browser tab (when ``account_id`` is missing
from args) and enforces **all** declared rate limits *before* ``run()``
executes.  Records each action *after* ``run()`` returns a success
status.

This hook is discovered automatically by ``script.py``'s
``_load_default_hooks()`` — no manual registration needed.
"""

from __future__ import annotations

import asyncio
import logging
from typing import Any

from framework.rate_limiter import SocialRateLimiter

logger = logging.getLogger(__name__)

# ── Lightweight identity JS (current-page only, no navigation) ──────
# These extract the logged-in account from the page's nav elements.
# If the nav isn't present on the current page, they return a non-ok
# status and we fall back to "unknown" (limits still apply globally).

IDENTITY_JS: dict[str, str] = {
    "linkedin": """(function () {
  var candidates = document.querySelectorAll('a[href*="/in/"]');
  for (var i = 0; i < candidates.length; i++) {
    var a = candidates[i];
    if (a.closest('nav, header, .global-nav, .feed-identity-module, .scaffold-layout__aside, [data-test-global-nav], #global-nav')) {
      var match = (a.href || '').match(/\\/in\\/([^\\/\\?#]+)/);
      if (match) return { status: 'ok', account_id: 'https://www.linkedin.com/in/' + match[1] + '/' };
    }
  }
  if (candidates.length === 0) return { status: 'no_profile_link' };
  var first = (candidates[0].href || '').match(/\\/in\\/([^\\/\\?#]+)/);
  if (first) return { status: 'ok', account_id: 'https://www.linkedin.com/in/' + first[1] + '/' };
  return { status: 'no_profile_link' };
})();""",
    "instagram": """(function () {
  var profileLink = document.querySelector('a[href$="/accounts/edit/"]');
  if (profileLink) {
    var parts = location.pathname.split('/').filter(Boolean);
    if (parts.length === 1) return { status: 'ok', account_id: '@' + parts[0] };
  }
  var settingsLink = document.querySelector('a[href="/accounts/edit/"], a[href*="/accounts/"]');
  if (settingsLink) {
    var imgs = document.querySelectorAll('img[alt]');
    for (var i = 0; i < imgs.length; i++) {
      var alt = (imgs[i].alt || '').trim();
      var parent = imgs[i].closest('a[href^="/"]');
      if (parent) {
        var match = (parent.getAttribute('href') || '').match(/^\\/([^\\/\\?#]+)\\//);
        if (match && match[1] !== 'explore' && match[1] !== 'direct' && match[1] !== 'reels') {
          return { status: 'ok', account_id: '@' + match[1] };
        }
      }
    }
  }
  var moreMenu = document.querySelector('[aria-label="Settings"]') || document.querySelector('[aria-label="More"]');
  if (moreMenu) {
    var navLinks = document.querySelectorAll('nav a[href^="/"]');
    for (var j = 0; j < navLinks.length; j++) {
      var href = navLinks[j].getAttribute('href') || '';
      var m = href.match(/^\\/([a-zA-Z0-9._]+)\\/$/);
      if (m && m[1] !== 'explore' && m[1] !== 'direct' && m[1] !== 'reels' && m[1] !== 'accounts') {
        return { status: 'ok', account_id: '@' + m[1] };
      }
    }
  }
  return { status: 'no_handle' };
})();""",
    "x": """(function () {
  var profileLink = document.querySelector('a[data-testid="AppTabBar_Profile_Link"]');
  if (profileLink) {
    var match = (profileLink.getAttribute('href') || '').match(/^\\/([^\\/\\?#]+)/);
    if (match) return { status: 'ok', account_id: '@' + match[1] };
  }
  var switcher = document.querySelector('[data-testid="SideNav_AccountSwitcher_Button"]');
  if (switcher) {
    var spans = switcher.querySelectorAll('span');
    for (var i = 0; i < spans.length; i++) {
      var text = (spans[i].textContent || '').trim();
      if (text.startsWith('@')) return { status: 'ok', account_id: text };
    }
  }
  return { status: 'no_handle' };
})();""",
}

_DEFAULT_SUCCESS_STATUSES = frozenset({"ok", "sent", "pending"})

# Ceiling for waiting out a "too_fast" pacing gap in-process (see before_run).
# Covers the common 45-60s min-delay configs; anything longer returns
# rate_limited so the agent schedules a trigger instead of blocking.
_TOO_FAST_ABSORB_S = 90.0

RATE_LIMIT_GUIDANCE = (
    "STOP. This rate limit is configured by the user and must be respected. "
    "Do NOT retry, loop, or attempt to circumvent it. "
    "You MUST use set_trigger to schedule a trigger that resumes this work "
    "after retry_after_seconds has elapsed. "
    "If running a campaign with remaining targets, calculate the required "
    "pacing from the observed limits (e.g. hourly_limit=10 with 50 targets "
    "→ set_trigger every ~6 minutes per target, or batch 10 then set_trigger "
    "for retry_after_seconds) and create the trigger NOW before ending this turn. "
    "Exceeding these limits risks getting the user's account banned."
)

_TARGET_ID_KEYS = ("target_id", "profile_url", "tweet_url", "post_url", "handle")


def _get_actions(module: Any) -> list[dict[str, Any]]:
    """Read rate-limited actions from the module.

    Supports ``RATE_LIMITED_ACTIONS`` (list) or ``RATE_LIMITED_ACTION``
    (single dict) for backward compatibility.
    """
    actions = getattr(module, "RATE_LIMITED_ACTIONS", None)
    if actions is not None:
        return list(actions)
    single = getattr(module, "RATE_LIMITED_ACTION", None)
    if single is not None:
        return [single]
    return []


async def _detect_identity(bridge: Any, tab_id: int, platform: str) -> str | None:
    """Run lightweight identity JS on the current tab. Returns account_id or None."""
    js = IDENTITY_JS.get(platform)
    if js is None:
        return None
    try:
        raw = await bridge.evaluate(tab_id, js)
        result = (raw or {}).get("result", {})
        if isinstance(result, dict) and result.get("status") == "ok":
            return result.get("account_id")
    except Exception:
        logger.debug("identity detection failed for platform=%s", platform, exc_info=True)
    return None


async def before_run(module: Any, bsc: Any, bridge: Any) -> dict | None:
    """Enforce rate limits before script execution.

    Reads rate-limited actions from *module*.  If absent, returns
    ``None`` (no-op).  Otherwise auto-detects identity and checks
    every declared limit.  Returns a ``rate_limited`` result dict to
    short-circuit on the **first** limit hit, or ``None`` to proceed.
    """
    actions = _get_actions(module)
    if not actions:
        return None

    platform = actions[0]["platform"]

    account_id = (bsc.args or {}).get("account_id", "unknown")
    if account_id == "unknown":
        detected = await _detect_identity(bridge, bsc.tab_id, platform)
        if detected:
            account_id = detected
            bsc.args["account_id"] = account_id

    limiter = SocialRateLimiter()

    for action in actions:
        action_type = action["action_type"]
        check = limiter.check(action.get("platform", platform), account_id, action_type)
        # Absorb SHORT pacing gaps ("too_fast" = the configured min-delay
        # between actions) in-process instead of bouncing a rate_limited
        # result back through a full agent round-trip: the wait happens
        # either way, but a bounce costs an extra LLM turn per send and, in
        # batch workers, turns every second send into a retry loop. This
        # WAITS OUT the user-configured limit (never bypasses it) and only
        # for small gaps — hourly/daily caps still short-circuit below so
        # the agent schedules a trigger instead of blocking for an hour.
        if not check["allowed"] and check.get("reason") == "too_fast" and 0 < float(check.get("retry_after_seconds") or 0) <= _TOO_FAST_ABSORB_S:
            wait_s = float(check["retry_after_seconds"]) + 1.0
            logger.info(
                "rate_limit_hook absorbing too_fast gap: platform=%s account=%s action=%s wait=%.1fs",
                action.get("platform", platform),
                account_id,
                action_type,
                wait_s,
            )
            await asyncio.sleep(wait_s)
            check = limiter.check(action.get("platform", platform), account_id, action_type)
        if not check["allowed"]:
            logger.info(
                "rate_limit_hook blocked: platform=%s account=%s action=%s reason=%s",
                action.get("platform", platform),
                account_id,
                action_type,
                check.get("reason"),
            )
            return {
                "status": "rate_limited",
                "action_type": action_type,
                "platform": action.get("platform", platform),
                "halt_campaign": check.get("halt_campaign", True),
                **{k: v for k, v in check.items() if k != "allowed"},
                "guidance": RATE_LIMIT_GUIDANCE,
            }

    bsc._rate_hook = {
        "limiter": limiter,
        "platform": platform,
        "account_id": account_id,
        "actions": actions,
        "success_statuses": actions[0].get("record_on_status", _DEFAULT_SUCCESS_STATUSES),
    }
    return None


async def after_run(module: Any, bsc: Any, bridge: Any, result: dict) -> dict:
    """Record successful actions in the rate limiter."""
    hook_data = getattr(bsc, "_rate_hook", None)
    if hook_data is None:
        return result

    status = result.get("status", "")
    if status not in hook_data["success_statuses"]:
        return result

    target_id = None
    for key in _TARGET_ID_KEYS:
        target_id = result.get(key)
        if target_id:
            break

    limiter = hook_data["limiter"]
    account_id = hook_data["account_id"]
    platform = hook_data["platform"]

    for action in hook_data["actions"]:
        try:
            limiter.record(
                action.get("platform", platform),
                account_id,
                action["action_type"],
                target_id=target_id,
            )
        except Exception:
            logger.warning("rate_limit_hook record() failed for %s", action["action_type"], exc_info=True)

    return result
