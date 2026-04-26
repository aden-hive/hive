"""Client metadata for OpenID Connect RP-Initiated Logout 1.0.

https://openid.net/specs/openid-connect-rpinitiated-1_0.html
"""

from joserfc.errors import InvalidClaimError

from authlib.common.security import is_secure_transport
from authlib.common.urls import is_valid_url
from authlib.oauth2.claims import BaseClaims


class ClientMetadataClaims(BaseClaims):
    """Client metadata for OpenID Connect RP-Initiated Logout 1.0.

    This can be used with :ref:`specs/rfc7591` and :ref:`specs/rfc7592` endpoints::

        server.register_endpoint(
            ClientRegistrationEndpoint(
                claims_classes=[
                    rfc7591.ClientMetadataClaims,
                    oidc.registration.ClientMetadataClaims,
                    oidc.rpinitiated.ClientMetadataClaims,
                ]
            )
        )
    """

    REGISTERED_CLAIMS = [
        "post_logout_redirect_uris",
    ]

    def validate(self, now=None, leeway=0):
        super().validate(now, leeway)
        self._validate_post_logout_redirect_uris()

    def _validate_post_logout_redirect_uris(self):
        # rpinitiated §3.1: "post_logout_redirect_uris - Array of URLs supplied
        # by the RP to which it MAY request that the End-User's User Agent be
        # redirected using the post_logout_redirect_uri parameter after a
        # logout has been performed. These URLs SHOULD use the https scheme
        # [...]; however, they MAY use the http scheme, provided that the
        # Client Type is confidential."
        uris = self.get("post_logout_redirect_uris")
        if not uris:
            return

        is_public = self.get("token_endpoint_auth_method") == "none"

        for uri in uris:
            if not is_valid_url(uri):
                raise InvalidClaimError("post_logout_redirect_uris")

            if is_public and not is_secure_transport(uri):
                raise ValueError(
                    '"post_logout_redirect_uris" MUST use "https" scheme for public clients'
                )
