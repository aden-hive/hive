"""authlib.oidc.rpinitiated.
~~~~~~~~~~~~~~~~~~~~~~~~~~~

OpenID Connect RP-Initiated Logout 1.0 Implementation.

https://openid.net/specs/openid-connect-rpinitiated-1_0.html
"""

from .discovery import OpenIDProviderMetadata
from .end_session import EndSessionEndpoint
from .end_session import EndSessionRequest
from .registration import ClientMetadataClaims

__all__ = [
    "EndSessionEndpoint",
    "EndSessionRequest",
    "ClientMetadataClaims",
    "OpenIDProviderMetadata",
]
