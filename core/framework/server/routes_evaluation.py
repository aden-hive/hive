"""Evaluation routes — query evaluation history and improvement plans."""

import logging

from aiohttp import web

from framework.runtime.evaluation import EvaluationStore, ExecutionEvaluator
from framework.server.app import resolve_session

logger = logging.getLogger(__name__)

# Shared store instance (stateless — reads from disk)
_store = EvaluationStore()
_evaluator = ExecutionEvaluator(store=_store)


async def handle_evaluation_history(request: web.Request) -> web.Response:
    """GET /api/sessions/{session_id}/evaluations?stream_id=...&limit=50

    Returns recent evaluation results for a stream.
    """
    session, err = resolve_session(request)
    if err:
        return err

    stream_id = request.query.get("stream_id", "")
    if not stream_id:
        return web.json_response({"error": "stream_id query param required"}, status=400)

    limit = int(request.query.get("limit", "50"))
    history = _store.load_history(stream_id, limit=limit)
    return web.json_response({"stream_id": stream_id, "evaluations": history})


async def handle_improvement_plan(request: web.Request) -> web.Response:
    """GET /api/sessions/{session_id}/improvement-plan?stream_id=...

    Diagnoses recent evaluation history and returns actionable recommendations.
    """
    session, err = resolve_session(request)
    if err:
        return err

    stream_id = request.query.get("stream_id", "")
    if not stream_id:
        return web.json_response({"error": "stream_id query param required"}, status=400)

    window = int(request.query.get("window", "10"))
    plan = _evaluator.diagnose(stream_id, window=window)
    return web.json_response({"stream_id": stream_id, "plan": plan.to_dict()})


def register_routes(app: web.Application) -> None:
    """Register evaluation routes."""
    app.router.add_get(
        "/api/sessions/{session_id}/evaluations",
        handle_evaluation_history,
    )
    app.router.add_get(
        "/api/sessions/{session_id}/improvement-plan",
        handle_improvement_plan,
    )
