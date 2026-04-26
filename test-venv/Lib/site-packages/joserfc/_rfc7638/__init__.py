import typing as t
import json
import hashlib
from collections import OrderedDict
from ..util import to_bytes, urlsafe_b64encode


def calculate_thumbprint(
    value: dict[str, t.Any],
    digest_method: t.Literal["sha256", "sha384", "sha512"] = "sha256",
) -> str:
    """Calculate the thumbprint value of a Key, per RFC 7638.

    .. code-block:: python

        from joserfc import jwk

        jwk.thumbprint({
            'kty': 'oct',
            'k': 'sTBpI_oCHSyW-n0exSwhzNHwU9FGRioPauxWA84bnRU',
        })
        # 'DCdRGGDKvhAJgmVlCp6tosc2T9ELtd30S_15vn8bhrI'
    """
    sorted_fields = sorted(value.keys())
    data = OrderedDict()
    for k in sorted_fields:
        data[k] = value[k]
    json_data = json.dumps(data, ensure_ascii=True, separators=(",", ":"))
    hash_value = hashlib.new(digest_method, to_bytes(json_data))
    digest_data = hash_value.digest()
    return urlsafe_b64encode(digest_data).decode("utf-8")
