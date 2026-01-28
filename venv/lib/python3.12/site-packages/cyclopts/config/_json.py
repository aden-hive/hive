import json
from pathlib import Path
from typing import Any

from cyclopts.config._common import ConfigFromFile
from cyclopts.exceptions import CoercionError


class Json(ConfigFromFile):
    def _load_config(self, path: Path) -> dict[str, Any]:
        with path.open() as f:
            try:
                return json.load(f)
            except json.JSONDecodeError as e:
                raise CoercionError from e
