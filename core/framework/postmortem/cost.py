"""Token-to-dollar estimation for a post-mortem.

Runtime step logs record token counts but not the model that produced them,
so cost is an *estimate* against one assumed model. The report always says
which model and where it came from, so a number is never mistaken for a
billed amount.
"""

from __future__ import annotations

from framework.llm.model_catalog import get_model_pricing


def resolve_model(explicit: str = "") -> tuple[str, str]:
    """Return ``(model_id, source)`` for cost estimation.

    Prefers an explicit CLI value, then the configured worker model (workers
    do the token-heavy execution), then the general default model.
    """
    if explicit:
        return explicit, "--model"

    # Imported lazily: reading config touches ~/.hive and is unnecessary when
    # the caller passed a model explicitly.
    from framework.config import get_preferred_model, get_preferred_worker_model

    try:
        worker = get_preferred_worker_model()
    except Exception:
        worker = None
    if worker:
        return worker, "configured worker model"

    try:
        preferred = get_preferred_model()
    except Exception:
        preferred = ""
    if preferred:
        return preferred, "configured default model"
    return "", ""


def estimate_cost(model_id: str, input_tokens: int, output_tokens: int) -> float | None:
    """Estimate USD for the given token counts, or ``None`` if unpriced.

    Assumes no prompt-cache hits, so this is an upper bound for runs that
    reuse a cached prefix.
    """
    if not model_id:
        return None
    pricing = get_model_pricing(model_id)
    if not pricing:
        # Providers are often addressed as "provider/model"; the catalog keys
        # on the bare id.
        if "/" in model_id:
            pricing = get_model_pricing(model_id.split("/", 1)[1])
        if not pricing:
            return None
    per_mtok_in = pricing.get("input", 0.0)
    per_mtok_out = pricing.get("output", 0.0)
    return (input_tokens * per_mtok_in + output_tokens * per_mtok_out) / 1_000_000
