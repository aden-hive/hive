from __future__ import annotations

import re
from typing import Any
from ..errors import InsecureClaimError


SENSITIVE_NAMES = ("password", "token", "secret", "secret_key", "api_key")
SENSITIVE_VALUES = re.compile(
    r"|".join(
        [
            # http://www.richardsramblings.com/regex/credit-card-numbers/
            r"\b(?:3[47]\d|(?:4\d|5[1-5]|65)\d{2}|6011)\d{12}\b",
            # various private keys
            r"-----BEGIN[A-Z ]+PRIVATE KEY-----.+-----END[A-Z ]+PRIVATE KEY-----",
            # social security numbers (US)
            r"^\b(?!(000|666|9))\d{3}-(?!00)\d{2}-(?!0000)\d{4}\b",
        ]
    ),
    re.DOTALL,
)


def check_sensitive_data(claims: dict[str, Any]) -> None:
    """
    Checks for sensitive data within a dictionary of claims and raises an
    error if any sensitive names or values are detected.

    :param claims: JWT claims to check for sensitive data
    :raises InsecureClaimError: if any sensitive names or values are detected
    """
    for k in claims:
        # check claims key name
        if k in SENSITIVE_NAMES:
            raise InsecureClaimError(k)

        # check claims values
        v = claims[k]
        if isinstance(v, str) and SENSITIVE_VALUES.search(v):
            raise InsecureClaimError(k)
