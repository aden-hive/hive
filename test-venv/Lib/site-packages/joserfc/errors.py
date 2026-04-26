from __future__ import annotations


class SecurityWarning(UserWarning):
    """Base class for warnings of security issues."""

    pass


class JoseError(Exception):
    """Base Exception for all errors in joserfc."""

    #: short-string error code
    error: str = ""
    #: long-string to describe this error
    description: str = ""

    def __init__(self, description: str | None = None):
        if description is not None:
            self.description = description

        message = "{}: {}".format(self.error, self.description)
        super(JoseError, self).__init__(message)


# --- Key related errors --- #


class KeyParameterError(JoseError):
    error = "key_parameter"


class MissingKeyError(JoseError):
    error = "missing_key"


class UnsupportedKeyUseError(KeyParameterError):
    error = "unsupported_key_use"


class UnsupportedKeyAlgorithmError(KeyParameterError):
    error = "unsupported_key_alg"


class UnsupportedKeyOperationError(KeyParameterError):
    error = "unsupported_key_operation"


class MissingKeyTypeError(KeyParameterError):
    error = "missing_key_type"


class InvalidKeyTypeError(KeyParameterError):
    error = "invalid_key_type"


class InvalidKeyIdError(JoseError):
    """This error is designed for Key Set. It is raised when a key
    can not be found with the given key ID."""

    error = "invalid_key_id"


class InvalidExchangeKeyError(JoseError):
    """This error is designed for EC and OKP keys. It is raised when
    exchanging derive key failed."""

    error = "invalid_exchange_key"
    description = "Invalid key for exchanging shared key"


# --- JWS & JWE related errors --- #


class DecodeError(JoseError):
    """This error is designed for both JWS and JWE. It is raised when deserialization
    and decryption fails.
    """

    error = "decode_error"


class MissingAlgorithmError(JoseError):
    """Raised when an algorithm ("alg") is missing."""

    error = "missing_algorithm"
    description = "Missing 'alg' value in header"


class ConflictAlgorithmError(JoseError):
    error = "conflict_algorithm"


class UnsupportedAlgorithmError(JoseError):
    """This error is designed for both JWS and JWE. It is raised when the
    given algorithm is not supported in the registry.
    """

    error = "unsupported_algorithm"


class InvalidHeaderValueError(JoseError):
    """Raised when the given header's value is invalid."""

    error = "invalid_header_value"


class UnsupportedHeaderError(JoseError):
    """Raised when an unsupported header is encountered."""

    error = "unsupported_header"


class MissingHeaderError(JoseError):
    """This error happens when the required header does not exist."""

    error = "missing_header"

    def __init__(self, key: str):
        description = f"Missing '{key}' value in header"
        super(MissingHeaderError, self).__init__(description=description)


class MissingCritHeaderError(JoseError):
    """This error happens when the critical header does not exist."""

    error = "missing_crit_header"

    def __init__(self, key: str):
        description = f"Missing critical '{key}' value in header"
        super(MissingCritHeaderError, self).__init__(description=description)


class MissingEncryptionError(JoseError):
    """This error is designed for JWE. It is raised when the 'enc' value
    in header is missing."""

    error = "missing_encryption"
    description = "Missing 'enc' value in header"


class InvalidKeyCurveError(JoseError):
    """This error is designed for JWS. It is raised when key's
    curve name does not match with the given algorithm.
    """

    error = "invalid_key_curve"


class InvalidKeyLengthError(JoseError):
    """This error is designed for JWE. It is raised when key's
    length does not align with the given algorithm.
    """

    error = "invalid_key_length"


class BadSignatureError(JoseError):
    """This error is designed for JWS. It is raised when signature
    does not match.
    """

    error = "bad_signature"


class ExceededSizeError(JoseError):
    """This error is designed for validating the token's content size.
    It raised when the data exceeds the maximum allowed length."""

    error = "exceeded_size"


class InvalidEncryptionAlgorithmError(JoseError):
    """This error is designed for JWE. It is raised when "enc" value
    does not work together with "alg" value.
    """

    error = "invalid_encryption_algorithm"


class InvalidEncryptedKeyError(JoseError):
    error = "invalid_encrypted_key"
    description = "JWE Encrypted Key value SHOULD be an empty octet sequence"


# --- JWT related errors --- #


class ClaimError(JoseError):
    """This a base error for JWT claims validation."""

    claim: str
    description = "Error claim: '{}'"

    def __init__(self, claim: str, description: str | None = None):
        self.claim = claim
        if description is None:
            description = self.description.format(claim)
        super(ClaimError, self).__init__(description=description)


class InvalidClaimError(ClaimError):
    """This error is designed for JWT. It raised when the claim contains
    invalid values or types."""

    error = "invalid_claim"
    description = "Invalid claim: '{}'"


class MissingClaimError(ClaimError):
    """This error is designed for JWT. It raised when the required
    claims are missing."""

    error = "missing_claim"
    description = "Missing claim: '{}'"


class InsecureClaimError(ClaimError):
    """This error is designed for JWT. It raised when the claim
    contains sensitive information."""

    error = "insecure_claim"
    description = "Insecure claim: '{}'"


class ExpiredTokenError(ClaimError):
    """This error is designed for JWT. It raised when the token is expired."""

    error = "expired_token"
    description = "The token is expired"


class InvalidPayloadError(JoseError):
    """This error is designed for JWT. It raised when the payload is
    not a valid JSON object."""

    error = "invalid_payload"


# compatibility
InvalidTokenError = InvalidClaimError
