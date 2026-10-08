"""Team email senders: a cloud-configured pool of "from" identities the
queen agents use to send email, with sender rotation.

The pool is defined on the Aden cloud (team scope) and pulled to the device
over the API-key-authed ``GET /v1/senders/runtime`` endpoint. This package
turns that pool into something the agent can use easily:

- :mod:`registry`  — load/cache the pool, resolve OAuth tokens.
- :mod:`providers` — dispatch a single send to the right provider API.
- :mod:`rotation`  — pick the next sender (round-robin / weighted /
  least-used) with per-day usage counters + daily-limit enforcement.
- :mod:`setup`     — create senders from an agent, handing off to the desktop
  form (pre-filled) for the auth steps only a human can do.
"""

from __future__ import annotations

from .registry import SenderConfig, SenderRegistry, get_registry
from .setup import setup_sender

__all__ = ["SenderConfig", "SenderRegistry", "get_registry", "setup_sender"]
