"""authlib.oidc.core.grants.code.
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

Implementation of Authentication using the Authorization Code Flow
per `Section 3.1`_.

.. _`Section 3.1`: https://openid.net/specs/openid-connect-core-1_0.html#CodeFlowAuth
"""

import logging

from joserfc import jwt

from authlib._joserfc_helpers import import_any_key
from authlib.oauth2.rfc6749 import OAuth2Request

from ..models import AuthorizationCodeMixin
from ._legacy import LegacyMixin
from .util import create_half_hash
from .util import is_openid_scope
from .util import validate_nonce
from .util import validate_request_prompt

log = logging.getLogger(__name__)


class OpenIDToken(LegacyMixin):
    def get_authorization_code_claims(self, authorization_code: AuthorizationCodeMixin):
        claims = {
            "nonce": authorization_code.get_nonce(),
            "auth_time": authorization_code.get_auth_time(),
        }

        if acr := authorization_code.get_acr():
            claims["acr"] = acr

        if amr := authorization_code.get_amr():
            claims["amr"] = amr
        return claims

    def generate_user_info(self, user, scope):
        """Provide user information for the given scope. Developers
        MUST implement this method in subclass, e.g.::

            from authlib.oidc.core import UserInfo


            def generate_user_info(self, user, scope):
                user_info = UserInfo(sub=user.id, name=user.name)
                if "email" in scope:
                    user_info["email"] = user.email
                return user_info

        :param user: user instance
        :param scope: scope of the token
        :return: ``authlib.oidc.core.UserInfo`` instance
        """
        raise NotImplementedError()

    def encode_id_token(self, token, request: OAuth2Request):
        alg = self.get_client_algorithm(request.client)
        header = self.get_encode_header(request.client)

        claims = self.get_compatible_claims(request)
        if request.authorization_code:
            claims.update(
                self.get_authorization_code_claims(request.authorization_code)
            )

        access_token = token.get("access_token")
        if access_token:
            at_hash = create_half_hash(access_token, alg)
            if at_hash is not None:
                claims["at_hash"] = at_hash.decode("utf-8")

        user_info = self.generate_user_info(request.user, token["scope"])
        claims.update(user_info)

        if alg == "none":
            private_key = None
        else:
            key = self.resolve_client_private_key(request.client)
            private_key = import_any_key(key)

        return jwt.encode(header, claims, private_key, [alg])

    def process_token(self, grant, response):
        _, token, _ = response
        scope = token.get("scope")
        if not scope or not is_openid_scope(scope):
            # standard authorization code flow
            return token

        request: OAuth2Request = grant.request
        id_token = self.encode_id_token(token, request)
        token["id_token"] = id_token
        return token

    def __call__(self, grant):
        grant.register_hook("after_create_token_response", self.process_token)


class OpenIDCode(OpenIDToken):
    """An extension from OpenID Connect for "grant_type=code" request. Developers
    MUST implement the missing methods::

        class MyOpenIDCode(OpenIDCode):
            def resolve_client_private_key(self, client):
                with open(jwks_file_path) as f:
                    data = json.load(f)
                return KeySet.import_key_set(data)

            def exists_nonce(self, nonce, request):
                return check_if_nonce_in_cache(request.payload.client_id, nonce)

            def generate_user_info(self, user, scope):
                return {...}

    The register this extension with AuthorizationCodeGrant::

        authorization_server.register_grant(
            AuthorizationCodeGrant, extensions=[MyOpenIDCode()]
        )
    """

    def __init__(self, require_nonce=False):
        self.require_nonce = require_nonce

    def exists_nonce(self, nonce, request):
        """Check if the given nonce is existing in your database. Developers
        MUST implement this method in subclass, e.g.::

            def exists_nonce(self, nonce, request):
                exists = AuthorizationCode.query.filter_by(
                    client_id=request.payload.client_id, nonce=nonce
                ).first()
                return bool(exists)

        :param nonce: A string of "nonce" parameter in request
        :param request: OAuth2Request instance
        :return: Boolean
        """
        raise NotImplementedError()

    def validate_openid_authorization_request(self, grant, redirect_uri):
        validate_nonce(grant.request, self.exists_nonce, self.require_nonce)

    def __call__(self, grant):
        grant.register_hook("after_create_token_response", self.process_token)
        if is_openid_scope(grant.request.payload.scope):
            grant.register_hook(
                "after_validate_authorization_request_payload",
                self.validate_openid_authorization_request,
            )
            grant.register_hook(
                "after_validate_consent_request", validate_request_prompt
            )
