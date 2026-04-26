from typing import Any

from joserfc.jwk import KeySet
from joserfc.jwk import import_key

from authlib.common.encoding import json_loads
from authlib.deprecate import deprecate
from authlib.jose import ECKey
from authlib.jose import OctKey
from authlib.jose import OKPKey
from authlib.jose import RSAKey


def import_any_key(data: Any):
    if isinstance(data, (OctKey, RSAKey, ECKey, OKPKey)):
        deprecate("Please use joserfc to import keys.", version="2.0.0")
        return import_key(data.as_dict(is_private=not data.public_only))

    if (
        isinstance(data, str)
        and data.strip().startswith("{")
        and data.strip().endswith("}")
    ):
        deprecate(
            "Please use OctKey, RSAKey, ECKey, OKPKey, and KeySet directly.",
            version="2.0.0",
        )
        data = json_loads(data)

    if isinstance(data, (str, bytes)):
        deprecate(
            "Please use OctKey, RSAKey, ECKey, OKPKey, and KeySet directly.",
            version="2.0.0",
        )
        return import_key(data)

    elif isinstance(data, dict):
        if "keys" in data:
            deprecate(
                "Please `KeySet.import_key_set` from `joserfc.jwk` to import jwks.",
                version="2.0.0",
            )
            return KeySet.import_key_set(data)
        return import_key(data)
    return data
