import time
import warnings

from authlib.oauth2 import OAuth2Request


class LegacyMixin:
    DEFAULT_EXPIRES_IN = 3600

    def resolve_client_private_key(self, client):
        """Resolve the client private key for encoding ``id_token`` Developers
        MUST implement this method in subclass, e.g.::

            import json
            from joserfc.jwk import KeySet


            def resolve_client_private_key(self, client):
                with open(jwks_file_path) as f:
                    data = json.load(f)
                return KeySet.import_key_set(data)
        """
        config = self._compatible_resolve_jwt_config(None, client)
        return config["key"]

    def get_client_algorithm(self, client):
        """Return the algorithm for encoding ``id_token``. By default, it will
        use ``client.id_token_signed_response_alg``, if not defined, ``RS256``
        will be used. But you can override this method to customize the returned
        algorithm.
        """
        # Per OpenID Connect Registration 1.0 Section 2:
        # Use client's id_token_signed_response_alg if specified
        config = self._compatible_resolve_jwt_config(None, client)
        alg = config.get("alg")
        if alg:
            return alg

        if hasattr(client, "id_token_signed_response_alg"):
            return client.id_token_signed_response_alg or "RS256"
        return "RS256"

    def get_client_claims(self, client):
        """Return the default client claims for encoding the ``id_token``. Developers
        MUST implement this method in subclass, e.g.::

            def get_client_claims(self, client):
                return {
                    "iss": "your-service-url",
                    "aud": [client.get_client_id()],
                }
        """
        config = self._compatible_resolve_jwt_config(None, client)
        claims = {k: config[k] for k in config if k not in ["key", "alg"]}
        if "exp" in config:
            now = int(time.time())
            claims["exp"] = now + config["exp"]
        return claims

    def get_encode_header(self, client):
        config = self._compatible_resolve_jwt_config(None, client)
        kid = config.get("kid")
        header = {"alg": self.get_client_algorithm(client)}
        if kid:
            header["kid"] = kid
        return header

    def get_compatible_claims(self, request: OAuth2Request):
        now = int(time.time())

        claims = self.get_client_claims(request.client)
        claims.setdefault("iat", now)
        claims.setdefault("exp", now + self.DEFAULT_EXPIRES_IN)
        claims.setdefault("auth_time", now)

        # compatible code
        if "aud" not in claims and hasattr(self, "get_audiences"):
            warnings.warn(
                "get_audiences(self, request) is deprecated and will be removed in version 1.8. "
                "You can set the ``aud`` value in get_client_claims instead.",
                DeprecationWarning,
                stacklevel=2,
            )
            claims["aud"] = self.get_audiences(request)

        claims.setdefault("aud", [request.client.get_client_id()])
        return claims

    def _compatible_resolve_jwt_config(self, grant, client):
        if not hasattr(self, "get_jwt_config"):
            return {}

        warnings.warn(
            "get_jwt_config(self, grant) is deprecated and will be removed in version 1.8. "
            "Use resolve_client_private_key, get_client_claims, get_client_algorithm instead.",
            DeprecationWarning,
            stacklevel=2,
        )
        try:
            config = self.get_jwt_config(grant, client)
        except TypeError:
            config = self.get_jwt_config(grant)
        return config
