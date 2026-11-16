"""Ship the built dashboard inside the wheel, so an installed Hive serves it too.

The dashboard is built into ``frontend/dist`` (``npm run build`` in ``core/frontend``). When it
has been built, the wheel carries it as ``framework/server/frontend``, where the server looks
after the checkout paths. Without a build the wheel is still made, just without a dashboard.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from hatchling.builders.hooks.plugin.interface import BuildHookInterface


class FrontendBuildHook(BuildHookInterface):
    def initialize(self, version: str, build_data: dict[str, Any]) -> None:
        if self.target_name != "wheel":
            return
        dist = Path(self.root) / "frontend" / "dist"
        if (dist / "index.html").is_file():
            build_data["force_include"][str(dist)] = "framework/server/frontend"
        else:
            self.app.display_warning("frontend/dist is not built: this wheel has no dashboard (run `npm run build` in core/frontend)")
