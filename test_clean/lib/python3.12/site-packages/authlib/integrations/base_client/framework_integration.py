import json
import time


class FrameworkIntegration:
    expires_in = 3600

    def __init__(self, name, cache=None):
        self.name = name
        self.cache = cache

    def _get_cache_data(self, key):
        value = self.cache.get(key)
        if not value:
            return None
        try:
            return json.loads(value)
        except (TypeError, ValueError):
            return None

    def _clear_session_state(self, session):
        now = time.time()
        prefix = f"_state_{self.name}"
        for key in dict(session):
            if key.startswith(prefix):
                value = session[key]
                exp = value.get("exp")
                if not exp or exp < now:
                    session.pop(key)

    def get_state_data(self, session, state):
        key = f"_state_{self.name}_{state}"
        session_data = session.get(key)
        if not session_data:
            return None
        if self.cache:
            cached_value = self._get_cache_data(key)
        else:
            cached_value = session_data
        if cached_value:
            return cached_value.get("data")
        return None

    def set_state_data(self, session, state, data):
        key = f"_state_{self.name}_{state}"
        now = time.time()
        if self.cache:
            self.cache.set(key, json.dumps({"data": data}), self.expires_in)
            session[key] = {"exp": now + self.expires_in}
        else:
            session[key] = {"data": data, "exp": now + self.expires_in}

    def clear_state_data(self, session, state):
        key = f"_state_{self.name}_{state}"
        if self.cache:
            self.cache.delete(key)
        session.pop(key, None)
        self._clear_session_state(session)

    def update_token(self, token, refresh_token=None, access_token=None):
        raise NotImplementedError()

    @staticmethod
    def load_config(oauth, name, params):
        raise NotImplementedError()
