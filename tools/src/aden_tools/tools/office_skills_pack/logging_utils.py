from __future__ import annotations

import json
import logging
import time
from contextlib import contextmanager
from typing import Any, Dict, Iterator

logger = logging.getLogger("aden_tools.office_skills_pack")


@contextmanager
def tool_span(tool: str, fields: Dict[str, Any]) -> Iterator:
    t0 = time.time()
    state: Dict[str, Any] = {"status": "ok", "error_code": None, "output_path": None}

    def done(result: Dict[str, Any]) -> Dict[str, Any]:
        success = bool(result.get("success"))
        state["status"] = "ok" if success else "error"
        err = result.get("error") or {}
        state["error_code"] = err.get("code")
        state["output_path"] = result.get("output_path")
        return result

    try:
        yield done
        dt = int((time.time() - t0) * 1000)
        logger.info(json.dumps({"tool": tool, "duration_ms": dt, **state, **fields}))
    except Exception as e:
        dt = int((time.time() - t0) * 1000)
        logger.exception(
            json.dumps({"tool": tool, "status": "error", "duration_ms": dt, "error": str(e), **fields})
        )
        raise
