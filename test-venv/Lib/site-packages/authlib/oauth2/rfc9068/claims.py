from joserfc.errors import InvalidClaimError
from joserfc.jwt import JWTClaimsRegistry

from authlib.oauth2.claims import JWTClaims


class JWTAccessTokenClaimsValidator(JWTClaimsRegistry):
    def validate_auth_time(self, auth_time):
        if not isinstance(auth_time, (int, float)):
            raise InvalidClaimError("auth_time")
        self.check_value("auth_time", auth_time)

    def validate_amr(self, amr):
        if not isinstance(amr, list):
            raise InvalidClaimError("amr", amr)


class JWTAccessTokenClaims(JWTClaims):
    registry_cls = JWTAccessTokenClaimsValidator
    REGISTERED_CLAIMS = JWTClaims.REGISTERED_CLAIMS + [
        "client_id",
        "auth_time",
        "acr",
        "amr",
        "scope",
        "groups",
        "roles",
        "entitlements",
    ]

    def validate(self, **kwargs):
        typ = self.header.get("typ")
        if typ and typ.lower() not in ("at+jwt", "application/at+jwt"):
            raise InvalidClaimError("typ")
        super().validate(**kwargs)
