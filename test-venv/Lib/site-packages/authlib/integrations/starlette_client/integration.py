import json
import time
from collections.abc import Hashable
from typing import Any

from ..base_client import FrameworkIntegration


class StarletteIntegration(FrameworkIntegration):
    async def _get_cache_data(self, key: Hashable):
        value = await self.cache.get(key)
        if not value:
            return None
        try:
            return json.loads(value)
        except (TypeError, ValueError):
            return None

    async def get_state_data(
        self, session: dict[str, Any] | None, state: str
    ) -> dict[str, Any]:
        key = f"_state_{self.name}_{state}"
        if self.cache:
            # require a session-bound marker to prove the callback originates
            # from the user-agent that started the flow (RFC 6749 §10.12)
            if session is None or session.get(key) is None:
                return None
            value = await self._get_cache_data(key)
        elif session is not None:
            value = session.get(key)
        else:
            value = None

        if value:
            return value.get("data")
        return None

    async def set_state_data(
        self, session: dict[str, Any] | None, state: str, data: Any
    ):
        key_prefix = f"_state_{self.name}_"
        key = f"{key_prefix}{state}"
        now = time.time()
        if self.cache:
            await self.cache.set(key, json.dumps({"data": data}), self.expires_in)
            if session is not None:
                # clear old state data to avoid session size growing
                for old_key in list(session.keys()):
                    if old_key.startswith(key_prefix):
                        session.pop(old_key)
                session[key] = {"exp": now + self.expires_in}
        elif session is not None:
            # clear old state data to avoid session size growing
            for old_key in list(session.keys()):
                if old_key.startswith(key_prefix):
                    session.pop(old_key)
            session[key] = {"data": data, "exp": now + self.expires_in}

    async def clear_state_data(self, session: dict[str, Any] | None, state: str):
        key = f"_state_{self.name}_{state}"
        if self.cache:
            await self.cache.delete(key)
        if session is not None:
            session.pop(key, None)
            self._clear_session_state(session)

    def update_token(self, token, refresh_token=None, access_token=None):
        pass

    @staticmethod
    def load_config(oauth, name, params):
        if not oauth.config:
            return {}

        rv = {}
        for k in params:
            conf_key = f"{name}_{k}".upper()
            v = oauth.config.get(conf_key, default=None)
            if v is not None:
                rv[k] = v
        return rv
