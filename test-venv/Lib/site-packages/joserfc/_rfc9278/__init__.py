import typing as t
from .._rfc7638 import calculate_thumbprint

JWK_THUMBPRINT_URN = "urn:ietf:params:oauth:jwk-thumbprint"


def calculate_thumbprint_uri(
    value: dict[str, t.Any],
    digest_method: t.Literal["sha256", "sha384", "sha512"] = "sha256",
) -> str:
    """Calculate JWK thumbprint URI, defined by RFC9278.

    .. code-block:: python

        from joserfc import jwk

        jwk.thumbprint({
            'kty': 'oct',
            'k': 'sTBpI_oCHSyW-n0exSwhzNHwU9FGRioPauxWA84bnRU',
        })
        # 'urn:ietf:params:oauth:jwk-thumbprint:sha-256:DCdRGGDKvhAJgmVlCp6tosc2T9ELtd30S_15vn8bhrI'
    """
    thumbprint = calculate_thumbprint(value, digest_method=digest_method)
    return concat_thumbprint_uri(thumbprint, digest_method=digest_method)


def concat_thumbprint_uri(value: str, digest_method: t.Literal["sha256", "sha384", "sha512"]) -> str:
    method = digest_method.replace("sha", "sha-")
    return f"{JWK_THUMBPRINT_URN}:{method}:{value}"
