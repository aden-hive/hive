import time


class OAuth2Token(dict):
    def __init__(self, params):
        if params.get("expires_at"):
            try:
                params["expires_at"] = int(params["expires_at"])
            except ValueError:
                # If expires_at is not parseable, fall back to expires_in if available
                # Otherwise leave expires_at untouched
                if params.get("expires_in"):
                    params["expires_at"] = int(time.time()) + int(params["expires_in"])

        elif params.get("expires_in"):
            params["expires_at"] = int(time.time()) + int(params["expires_in"])

        super().__init__(params)

    def is_expired(self, leeway=60):
        expires_at = self.get("expires_at")
        if not expires_at:
            return None
        # Only check expiration if expires_at is an integer
        if not isinstance(expires_at, int):
            return None
        # small timedelta to consider token as expired before it actually expires
        expiration_threshold = expires_at - leeway
        return expiration_threshold < time.time()

    @classmethod
    def from_dict(cls, token):
        if isinstance(token, dict) and not isinstance(token, cls):
            token = cls(token)
        return token
