"""OpenID Connect RP-Initiated Logout 1.0 implementation.

https://openid.net/specs/openid-connect-rpinitiated-1_0.html
"""

from __future__ import annotations

from dataclasses import dataclass
from dataclasses import field
from typing import TYPE_CHECKING
from typing import Any

from joserfc import jwt
from joserfc.errors import JoseError
from joserfc.jwk import KeySet
from joserfc.jws import JWSRegistry

from authlib.common.urls import add_params_to_uri
from authlib.oauth2.rfc6749.endpoint import Endpoint
from authlib.oauth2.rfc6749.endpoint import EndpointRequest
from authlib.oauth2.rfc6749.errors import InvalidRequestError

if TYPE_CHECKING:
    from authlib.oauth2.rfc6749.requests import OAuth2Request


class _NonExpiringClaimsRegistry(jwt.JWTClaimsRegistry):
    """Claims registry that skips expiration validation."""

    # rpinitiated §2: "The OP SHOULD accept ID Tokens when the RP identified by the
    # ID Token's aud claim and/or sid claim has a current session or had a
    # recent session at the OP, even when the exp time has passed."
    def validate_exp(self, value: int) -> None:
        pass


@dataclass
class EndSessionRequest(EndpointRequest):
    """Validated end session request data.

    This object is returned by :meth:`EndSessionEndpoint.validate_request`
    and contains all the validated information from the logout request.
    """

    id_token_claims: dict | None = field(default=None, repr=False)
    redirect_uri: str | None = None
    logout_hint: str | None = None
    ui_locales: str | None = None

    @property
    def needs_confirmation(self) -> bool:
        """Whether user confirmation is recommended before logout."""

        # rpinitiated §6: "Logout requests without a valid id_token_hint value are a
        # potential means of denial of service; therefore, OPs should obtain
        # explicit confirmation from the End-User before acting upon them."
        return self.id_token_claims is None


class EndSessionEndpoint(Endpoint):
    """OpenID Connect RP-Initiated Logout endpoint.

    This endpoint follows a two-phase pattern for interactive flows:

    1. Call ``server.validate_endpoint_request("end_session")`` to validate
       the request and get an :class:`EndSessionRequest`
    2. Check ``end_session_request.needs_confirmation`` and show UI if needed
    3. Call ``server.create_endpoint_response("end_session", end_session_request)``
       to execute logout and create the response

    Example usage::

        class MyEndSessionEndpoint(EndSessionEndpoint):
            def get_server_jwks(self):
                return load_jwks()

            def end_session(self, end_session_request):
                session.clear()


        server.register_endpoint(MyEndSessionEndpoint)


        @app.route("/logout", methods=["GET", "POST"])
        def logout():
            try:
                req = server.validate_endpoint_request("end_session")
            except OAuth2Error as error:
                return server.handle_error_response(None, error)

            if req.needs_confirmation and request.method == "GET":
                return render_template("confirm_logout.html", client=req.client)

            return server.create_endpoint_response(
                "end_session", req
            ) or render_template("logged_out.html")

    For non-interactive usage (no confirmation page), use the standard pattern::

        @app.route("/logout", methods=["GET", "POST"])
        def logout():
            return server.create_endpoint_response("end_session") or render_template(
                "logged_out.html"
            )
    """

    ENDPOINT_NAME = "end_session"

    def validate_request(self, request: OAuth2Request) -> EndSessionRequest:
        """Validate an end session request.

        :param request: The OAuth2Request to validate
        :returns: EndSessionRequest with validated data
        :raises InvalidRequestError: If validation fails
        """
        data = request.payload.data

        id_token_hint = data.get("id_token_hint")
        client_id = data.get("client_id")
        post_logout_redirect_uri = data.get("post_logout_redirect_uri")
        state = data.get("state")
        logout_hint = data.get("logout_hint")
        ui_locales = data.get("ui_locales")

        # rpinitiated §2: "When an id_token_hint parameter is present, the OP MUST
        # validate that it was the issuer of the ID Token."
        id_token_claims = None
        if id_token_hint:
            id_token_claims = self._validate_id_token_hint(id_token_hint)

        # Resolve client
        client = None
        if client_id:
            client = self.server.query_client(client_id)
        elif id_token_claims:
            client = self.resolve_client_from_id_token_claims(id_token_claims)

        # rpinitiated §2: "When both client_id and id_token_hint are present, the OP
        # MUST verify that the Client Identifier matches the one used as the
        # audience of the ID Token."
        if client_id and id_token_claims:
            aud = id_token_claims.get("aud")
            aud_list = [aud] if isinstance(aud, str) else (aud or [])
            if client_id not in aud_list:
                raise InvalidRequestError("'client_id' does not match 'aud' claim")

        # rpinitiated §3: "The OP MUST NOT perform post-logout redirection if
        # the post_logout_redirect_uri value supplied does not exactly match
        # one of the previously registered post_logout_redirect_uris values."
        redirect_uri = None
        if (
            post_logout_redirect_uri
            and client
            and self._is_valid_post_logout_redirect_uri(
                client, post_logout_redirect_uri
            )
            and (
                id_token_claims
                or self.is_post_logout_redirect_uri_legitimate(
                    request, post_logout_redirect_uri, client, logout_hint
                )
            )
        ):
            redirect_uri = post_logout_redirect_uri
            # rpinitiated §3: "If the post_logout_redirect_uri value is provided
            # and the preceding conditions are met, the OP MUST include the
            # state value if the RP's initial Logout Request included state."
            if state:
                redirect_uri = add_params_to_uri(redirect_uri, {"state": state})

        return EndSessionRequest(
            request=request,
            client=client,
            id_token_claims=id_token_claims,
            redirect_uri=redirect_uri,
            logout_hint=logout_hint,
            ui_locales=ui_locales,
        )

    def create_response(
        self, validated_request: EndSessionRequest
    ) -> tuple[int, Any, list[tuple[str, str]]] | None:
        """Create the end session HTTP response.

        Executes the logout via :meth:`end_session`, then returns a redirect
        response if a valid redirect_uri is present, or None to let the
        application provide its own response.

        :param validated_request: The validated EndSessionRequest
        :returns: Tuple of (status_code, body, headers) for redirect, or None
        """
        req: EndSessionRequest = validated_request  # type: ignore[assignment]
        self.end_session(req)

        if req.redirect_uri:
            return 302, "", [("Location", req.redirect_uri)]
        return None

    def _validate_id_token_hint(self, id_token_hint: str) -> dict:
        """Validate that the OP was the issuer of the ID Token."""
        # rpinitiated §2: "When an id_token_hint parameter is present, the OP MUST
        # validate that it was the issuer of the ID Token."
        # This is done by verifying the signature against the server's JWKS.
        jwks = self.get_server_jwks()
        if isinstance(jwks, dict):
            jwks = KeySet.import_key_set(jwks)

        # rpinitiated §4: "When the OP detects errors in the RP-Initiated
        # Logout request, the OP MUST not perform post-logout redirection."
        try:
            token = jwt.decode(id_token_hint, jwks, algorithms=self.get_algorithms())
            claims_registry = _NonExpiringClaimsRegistry(nbf={"essential": False})
            claims_registry.validate(token.claims)
        except JoseError as exc:
            raise InvalidRequestError(exc.description) from exc

        return dict(token.claims)

    def resolve_client_from_id_token_claims(self, id_token_claims: dict) -> Any | None:
        """Resolve client from id_token aud claim.

        When aud is a single string, resolves the client directly.
        When aud is a list, returns None (ambiguous case).
        Override for custom resolution logic.
        """
        aud = id_token_claims.get("aud")
        if isinstance(aud, str):
            return self.server.query_client(aud)
        return None

    def _is_valid_post_logout_redirect_uri(
        self, client, post_logout_redirect_uri: str
    ) -> bool:
        """Check if post_logout_redirect_uri is registered for the client."""
        registered_uris = client.client_metadata.get("post_logout_redirect_uris", [])
        return post_logout_redirect_uri in registered_uris

    def is_post_logout_redirect_uri_legitimate(
        self,
        request: OAuth2Request,
        post_logout_redirect_uri: str,
        client,
        logout_hint: str | None,
    ) -> bool:
        """Confirm redirect_uri legitimacy when no id_token_hint is provided.

        Override if you have alternative confirmation mechanisms, e.g.::

            def is_post_logout_redirect_uri_legitimate(self, ...):
                return client and client.is_trusted

        By default returns False (no redirection without id_token_hint).
        """
        # rpinitiated §3: "if it is not supplied with post_logout_redirect_uri,
        # the OP MUST NOT perform post-logout redirection unless the OP has
        # other means of confirming the legitimacy"
        return False

    def get_server_jwks(self) -> dict | KeySet:
        """Return the server's JSON Web Key Set for validating ID tokens."""
        raise NotImplementedError()

    def get_algorithms(self) -> list[str]:
        """Return the list of allowed algorithms for ID token validation.

        By default, returns all algorithms compatible with the keys in the JWKS.
        Override to restrict to specific algorithms.
        """
        jwks = self.get_server_jwks()
        if isinstance(jwks, dict):
            jwks = KeySet.import_key_set(jwks)
        return [alg.name for alg in JWSRegistry.filter_algorithms(jwks)]

    def end_session(self, end_session_request: EndSessionRequest) -> None:
        """Terminate the user's session.

        Implement this method to perform the actual logout logic,
        such as clearing session data, revoking tokens, etc.

        Use ``end_session_request.logout_hint`` to help identify the user
        (e.g. email, username) when no ``id_token_hint`` is provided.

        :param end_session_request: The validated EndSessionRequest
        """
        raise NotImplementedError()
