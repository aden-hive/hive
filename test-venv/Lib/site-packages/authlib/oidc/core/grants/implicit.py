import logging
import warnings

from joserfc import jwt

from authlib._joserfc_helpers import import_any_key
from authlib.oauth2.rfc6749 import AccessDeniedError
from authlib.oauth2.rfc6749 import ImplicitGrant
from authlib.oauth2.rfc6749 import InvalidScopeError
from authlib.oauth2.rfc6749 import OAuth2Error
from authlib.oauth2.rfc6749.errors import InvalidRequestError
from authlib.oauth2.rfc6749.hooks import hooked

from ._legacy import LegacyMixin
from .util import create_half_hash
from .util import create_response_mode_response
from .util import is_openid_scope
from .util import validate_nonce
from .util import validate_request_prompt

log = logging.getLogger(__name__)


class OpenIDImplicitGrant(LegacyMixin, ImplicitGrant):
    RESPONSE_TYPES = {"id_token token", "id_token"}
    DEFAULT_RESPONSE_MODE = "fragment"

    def exists_nonce(self, nonce, request):
        """Check if the given nonce is existing in your database. Developers
        should implement this method in subclass, e.g.::

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

    def get_audiences(self, request):
        """Parse `aud` value for id_token, default value is client id. Developers
        MAY rewrite this method to provide a customized audience value.
        """
        client = request.client
        return [client.get_client_id()]

    def validate_authorization_request(self):
        if not is_openid_scope(self.request.payload.scope):
            raise InvalidScopeError(
                "Missing 'openid' scope",
                redirect_uri=self.request.payload.redirect_uri,
                redirect_fragment=True,
            )
        redirect_uri = super().validate_authorization_request()
        try:
            validate_nonce(self.request, self.exists_nonce, required=True)
        except OAuth2Error as error:
            error.redirect_uri = redirect_uri
            error.redirect_fragment = True
            raise error
        return redirect_uri

    @hooked
    def validate_consent_request(self):
        redirect_uri = self.validate_authorization_request()
        validate_request_prompt(self, redirect_uri, redirect_fragment=True)
        return redirect_uri

    def create_authorization_response(self, redirect_uri, grant_user):
        state = self.request.payload.state
        if grant_user:
            params = self.create_granted_params(grant_user)
            if state:
                params.append(("state", state))
        else:
            error = AccessDeniedError()
            params = error.get_body()

        # http://openid.net/specs/oauth-v2-multiple-response-types-1_0.html#ResponseModes
        response_mode = self.request.payload.data.get(
            "response_mode", self.DEFAULT_RESPONSE_MODE
        )
        return create_response_mode_response(
            redirect_uri=redirect_uri,
            params=params,
            response_mode=response_mode,
        )

    def create_granted_params(self, grant_user):
        self.request.user = grant_user
        client = self.request.client
        token = self.generate_token(
            user=grant_user,
            scope=self.request.payload.scope,
            include_refresh_token=False,
        )
        if self.request.payload.response_type == "id_token":
            token = {
                "expires_in": token["expires_in"],
                "scope": token["scope"],
            }
            token = self.process_implicit_token(token)
        else:
            log.debug("Grant token %r to %r", token, client)
            self.server.save_token(token, self.request)
            token = self.process_implicit_token(token)
        params = [(k, token[k]) for k in token]
        return params

    def process_implicit_token(self, token, code=None):
        alg = self.get_client_algorithm(self.request.client)
        if alg == "none":
            # According to oidc-registration §2 the 'none' alg is not valid in
            # implicit flows:
            #    The value none MUST NOT be used as the ID Token alg value unless
            #    the Client uses only Response Types that return no ID Token from
            #    the Authorization Endpoint (such as when only using the
            #    Authorization Code Flow).
            raise InvalidRequestError(
                "id_token must be signed in implicit flows",
                redirect_uri=self.request.payload.redirect_uri,
                redirect_fragment=True,
            )

        claims = self.get_compatible_claims(self.request)
        nonce = self.request.payload.data.get("nonce")
        if nonce:
            claims["nonce"] = nonce

        if code is not None:
            c_hash = create_half_hash(code, alg)
            if c_hash is not None:
                claims["c_hash"] = c_hash.decode("utf-8")

        access_token = token.get("access_token")
        if access_token:
            at_hash = create_half_hash(access_token, alg)
            if at_hash is not None:
                claims["at_hash"] = at_hash.decode("utf-8")

        user_info = self.generate_user_info(self.request.user, token["scope"])
        claims.update(user_info)
        key = self.resolve_client_private_key(self.request.client)
        private_key = import_any_key(key)
        header = self.get_encode_header(self.request.client)
        id_token = jwt.encode(header, claims, private_key, [alg])
        token["id_token"] = id_token
        return token

    def _compatible_resolve_jwt_config(self, grant, client):
        if not hasattr(self, "get_jwt_config"):
            return {}
        warnings.warn(
            "get_jwt_config(self, client) is deprecated and will be removed in version 1.8. "
            "Use resolve_client_private_key, get_client_claims, get_client_algorithm instead.",
            DeprecationWarning,
            stacklevel=2,
        )
        try:
            config = self.get_jwt_config(client)
        except TypeError:
            config = self.get_jwt_config()
        return config
