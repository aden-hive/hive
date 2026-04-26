from joserfc import jwt
from joserfc.errors import InvalidKeyIdError
from joserfc.jwk import KeySet

from authlib.common.security import generate_token
from authlib.common.urls import add_params_to_uri
from authlib.oidc.core import CodeIDToken
from authlib.oidc.core import ImplicitIDToken
from authlib.oidc.core import UserInfo

__all__ = ["AsyncOpenIDMixin"]


class AsyncOpenIDMixin:
    async def fetch_jwk_set(self, force=False):
        metadata = await self.load_server_metadata()
        jwk_set = metadata.get("jwks")
        if jwk_set and not force:
            return jwk_set

        uri = metadata.get("jwks_uri")
        if not uri:
            raise RuntimeError('Missing "jwks_uri" in metadata')

        async with self._get_session() as client:
            resp = await client.request("GET", uri, withhold_token=True)
            resp.raise_for_status()
            jwk_set = resp.json()

        self.server_metadata["jwks"] = jwk_set
        return jwk_set

    async def userinfo(self, **kwargs):
        """Fetch user info from ``userinfo_endpoint``."""
        metadata = await self.load_server_metadata()
        resp = await self.get(metadata["userinfo_endpoint"], **kwargs)
        resp.raise_for_status()
        data = resp.json()
        return UserInfo(data)

    async def parse_id_token(
        self, token, nonce, claims_options=None, claims_cls=None, leeway=120
    ):
        """Return an instance of UserInfo from token's ``id_token``."""
        claims_params = dict(
            nonce=nonce,
            client_id=self.client_id,
        )
        if claims_cls is None:
            if "access_token" in token:
                claims_params["access_token"] = token["access_token"]
                claims_cls = CodeIDToken
            else:
                claims_cls = ImplicitIDToken

        metadata = await self.load_server_metadata()
        if claims_options is None and "issuer" in metadata:
            claims_options = {"iss": {"values": [metadata["issuer"]]}}

        alg_values = metadata.get("id_token_signing_alg_values_supported")
        if not alg_values:
            alg_values = ["RS256"]

        jwks = await self.fetch_jwk_set()
        key_set = KeySet.import_key_set(jwks)
        try:
            token = jwt.decode(
                token["id_token"],
                key=key_set,
                algorithms=alg_values,
            )
        except InvalidKeyIdError:
            jwks = await self.fetch_jwk_set(force=True)
            key_set = KeySet.import_key_set(jwks)
            token = jwt.decode(
                token["id_token"],
                key=key_set,
                algorithms=alg_values,
            )

        claims = claims_cls(token.claims, token.header, claims_options, claims_params)
        # https://github.com/authlib/authlib/issues/259
        if claims.get("nonce_supported") is False:
            claims.params["nonce"] = None
        claims.validate(leeway=leeway)
        return UserInfo(claims)

    async def create_logout_url(
        self,
        post_logout_redirect_uri=None,
        id_token_hint=None,
        state=None,
        **kwargs,
    ):
        """Generate the end session URL for RP-Initiated Logout.

        :param post_logout_redirect_uri: URI to redirect after logout.
        :param id_token_hint: ID Token previously issued to the RP.
        :param state: Opaque value for maintaining state.
        :param kwargs: Extra parameters (client_id, logout_hint, ui_locales).
        :return: dict with 'url' and 'state' keys.
        """
        metadata = await self.load_server_metadata()
        end_session_endpoint = metadata.get("end_session_endpoint")

        if not end_session_endpoint:
            raise RuntimeError('Missing "end_session_endpoint" in metadata')

        params = {}
        if id_token_hint:
            params["id_token_hint"] = id_token_hint
        if post_logout_redirect_uri:
            params["post_logout_redirect_uri"] = post_logout_redirect_uri
            if state is None:
                state = generate_token(20)
            params["state"] = state

        for key in ("client_id", "logout_hint", "ui_locales"):
            if key in kwargs:
                params[key] = kwargs[key]

        url = add_params_to_uri(end_session_endpoint, params)
        return {"url": url, "state": state}
