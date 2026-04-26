from __future__ import annotations
import time
import json
import datetime
import calendar
from json import JSONEncoder
from typing import TypedDict, Type, Any, Callable
from ..util import to_bytes
from ..errors import (
    MissingClaimError,
    InvalidClaimError,
    ExpiredTokenError,
)

Claims = dict[str, Any]


def convert_claims(claims: Claims, encoder_cls: Type[JSONEncoder] | None = None) -> bytes:
    """Turn claims into bytes payload."""
    for k in ["exp", "iat", "nbf"]:
        claim = claims.get(k)
        if isinstance(claim, datetime.datetime):
            claims[k] = calendar.timegm(claim.utctimetuple())

    content = json.dumps(claims, ensure_ascii=False, separators=(",", ":"), cls=encoder_cls)
    return to_bytes(content)


#: http://openid.net/specs/openid-connect-core-1_0.html#IndividualClaimsRequests
class ClaimsOption(TypedDict, total=False):
    essential: bool
    allow_blank: bool | None
    value: str | int | bool
    values: list[str | int | bool] | list[str] | list[int] | list[bool]


class BaseClaimsRegistry:
    """Requesting "claims" for JWT with the given conditions."""

    def __init__(self, **kwargs: ClaimsOption):
        self.options = kwargs

    @property
    def essential_keys(self) -> set[str]:
        """Returns the essential claim names."""
        return {key for key in self.options if self.options[key].get("essential")}

    def check_value(self, claim_name: str, value: Any) -> None:
        """
        Validates a given claim value based on predefined options.

        :param claim_name: The name of the claim to validate.
        :param value: The value of the claim to be validated.
        :raises InvalidClaimError: If the value does not meet the claim's validation requirements.
        """
        option = self.options.get(claim_name)
        if not option:
            return

        allow_blank = option.get("allow_blank")
        if not allow_blank and value in (None, "", [], {}):
            raise InvalidClaimError(claim_name)

        option_values = option.get("values")

        if option_values is None:
            option_value = option.get("value")
            if option_value is not None:
                option_values = [option_value]

        if not option_values:
            return

        if isinstance(value, list):
            if not any(v in value for v in option_values):
                raise InvalidClaimError(claim_name)
        else:
            if value not in option_values:
                raise InvalidClaimError(claim_name)

    def validate(self, claims: dict[str, Any]) -> None:
        """
        Validates the provided claims against specified requirements and checks.

        :param claims: A dictionary containing claims to validate.
        :raises InvalidClaimError: Raised if any claim fails validation.
        :raises MissingClaimError: Raised if one or more essential keys are missing.
        """
        missed_keys = {key for key in self.essential_keys if claims.get(key) is None}
        if missed_keys:
            raise MissingClaimError(",".join(sorted(missed_keys)))

        for key in claims:
            value = claims[key]
            func = getattr(self, "validate_" + key, None)
            if func:
                func(value)
            elif key in self.options:
                self.check_value(key, value)


class JWTClaimsRegistry(BaseClaimsRegistry):
    """A claims registry for validating JWT claims.

    :param now: timestamp of "now" time
    :param leeway: leeway time in seconds
    :param kwargs: claims options
    """

    def __init__(self, now: int | Callable[[], int] | None = None, leeway: int = 0, **kwargs: ClaimsOption) -> None:
        if now is None:
            now = _generate_now
        self._now = now
        self.leeway = leeway
        super().__init__(**kwargs)

    @property
    def now(self) -> int:
        """Returns the current timestamp."""
        if callable(self._now):
            return self._now()
        return self._now

    def validate_exp(self, value: int) -> None:
        """The "exp" (expiration time) claim identifies the expiration time on
        or after which the JWT MUST NOT be accepted for processing.  The
        processing of the "exp" claim requires that the current date/time
        MUST be before the expiration date/time listed in the "exp" claim.
        Implementers MAY provide for some small leeway, usually no more than
        a few minutes, to account for clock skew.  Its value MUST be a number
        containing a NumericDate value.  Use of this claim is OPTIONAL.
        """
        if not _validate_numeric_time(value):
            raise InvalidClaimError("exp", "Claim 'exp' must be a NumericDate value")
        if value < (self.now - self.leeway):
            raise ExpiredTokenError("exp")
        self.check_value("exp", value)

    def validate_nbf(self, value: int) -> None:
        """The "nbf" (not before) claim identifies the time before which the JWT
        MUST NOT be accepted for processing.  The processing of the "nbf"
        claim requires that the current date/time MUST be after or equal to
        the not-before date/time listed in the "nbf" claim.  Implementers MAY
        provide for some small leeway, usually no more than a few minutes, to
        account for clock skew.  Its value MUST be a number containing a
        NumericDate value.  Use of this claim is OPTIONAL.
        """
        if not _validate_numeric_time(value):
            raise InvalidClaimError("nbf", "Claim 'nbf' must be a NumericDate value")
        if value > (self.now + self.leeway):
            raise InvalidClaimError("nbf", "The token is not yet valid")
        self.check_value("nbf", value)

    def validate_iat(self, value: int) -> None:
        """The "iat" (issued at) claim identifies the time at which the JWT was
        issued.  This claim can be used to determine the age of the JWT.  Its
        value MUST be a number containing a NumericDate value.  Use of this
        claim is OPTIONAL.
        """
        if not _validate_numeric_time(value):
            raise InvalidClaimError("iat", "Claim 'iat' must be a NumericDate value")
        if value > (self.now + self.leeway):
            raise InvalidClaimError("iat", "The token was issued in the future")
        self.check_value("iat", value)


def _validate_numeric_time(s: int) -> bool:
    return isinstance(s, (int, float))


def _generate_now() -> int:
    return int(time.time())
