"""The judge: a model, configured in the ``judge`` slot, that answers yes/no questions with a probability.

The slot names a protocol, an endpoint, a model and a key, so no vendor is built into Hive::

    "judge": {"protocol": "typesafe", "api_base": "<endpoint>", "model": "<model>", "api_key": "...", "threshold": 0.5}

The one protocol so far is ``typesafe``: TypeSafe's ``/systemone`` endpoint answering a "noul"
(probability) question, for example with Jev. The stall check asks it whether a queen announced
work and stopped; channels ask it through :meth:`ChannelHost.judge`. The slot is read on every
question, so changing it applies at once.
"""

from __future__ import annotations

import logging
from collections.abc import Awaitable, Callable
from typing import Any

logger = logging.getLogger(__name__)

# A judge that hangs must not hold whoever asked for long.
TIMEOUT_S = 20.0

# (slot, question, state, criteria) -> probability that the answer is yes
Protocol = Callable[[dict[str, Any], str, dict[str, Any], dict[str, str] | None], Awaitable[float]]


def slot() -> dict[str, Any] | None:
    """The configured ``judge`` slot, when it has an endpoint and a key."""
    from framework.config import get_hive_config

    s = get_hive_config().get("judge")
    if not isinstance(s, dict) or not s.get("api_base") or not s.get("api_key"):
        return None
    return s


async def typesafe(s: dict[str, Any], question: str, state: dict[str, Any], criteria: dict[str, str] | None) -> float:
    """p(yes) from a TypeSafe ``/systemone`` noul question."""
    import httpx

    q: dict[str, Any] = {"type": "noul", "instructions": question}
    if criteria:
        q["criteria"] = criteria
    body = {"state": state, "model": s.get("model"), "questions": {"answer": q}}
    async with httpx.AsyncClient(timeout=TIMEOUT_S) as client:
        resp = await client.post(
            f"{str(s['api_base']).rstrip('/')}/systemone",
            json=body,
            headers={"Authorization": f"Bearer {s['api_key']}"},
        )
        resp.raise_for_status()
        return float(resp.json()["answers"]["answer"]["noul"])


PROTOCOLS: dict[str, Protocol] = {"typesafe": typesafe}


async def ask(
    question: str,
    state: dict[str, Any],
    *,
    criteria: dict[str, str] | None = None,
    protocols: dict[str, Protocol] | None = None,
) -> float | None:
    """The judge's probability that the answer to ``question`` about ``state`` is yes.

    ``criteria`` may describe what counts as ``"true"`` and ``"false"``. ``None`` when no judge
    is configured, its protocol isn't supported, or the call fails; the reason is logged.
    """
    s = slot()
    if s is None:
        return None
    protocols = protocols or PROTOCOLS
    proto = protocols.get(str(s.get("protocol") or ""))
    if proto is None:
        logger.warning("judge: protocol %r is not supported (use one of %s)", s.get("protocol"), sorted(protocols))
        return None
    try:
        return await proto(s, question, state, criteria)
    except Exception as e:
        logger.info("judge: unavailable (%s: %s)", type(e).__name__, e)
        return None
