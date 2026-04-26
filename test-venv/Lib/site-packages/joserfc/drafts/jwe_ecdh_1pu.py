from __future__ import annotations
from .._rfc7516.models import Recipient, JWEKeyAgreement, JWEKeyWrapping, JWEEncModel
from .._rfc7518.jwe_algs import (
    A128KW,
    A192KW,
    A256KW,
)
from .._rfc7518.ec_key import ECKey
from .._rfc7518.derive_key import (
    derive_key_for_concat_kdf,
)
from .._rfc7518.jwe_encs import CBCHS2EncModel
from ..registry import HeaderParameter
from ..errors import InvalidEncryptionAlgorithmError


__all__ = ["ECDH1PUAlgModel", "register_ecdh_1pu", "JWE_ALG_MODELS"]


class ECDH1PUAlgModel(JWEKeyAgreement):
    """Key Agreement with Elliptic Curve Diffie-Hellman One-Pass Unified Model (ECDH-1PU)

    https://datatracker.ietf.org/doc/html/draft-madden-jose-ecdh-1pu-04
    """

    more_header_registry = {
        "epk": HeaderParameter("Ephemeral Public Key", "jwk", True),
        "apu": HeaderParameter("Agreement PartyUInfo", "str"),
        "apv": HeaderParameter("Agreement PartyVInfo", "str"),
        "skid": HeaderParameter("Sender Key ID", "str"),
    }
    key_types = ["EC", "OKP"]
    tag_aware = True

    def __init__(self, key_wrapping: JWEKeyWrapping | None):
        if key_wrapping is None:
            self.name = "ECDH-1PU"
            self.description = "ECDH-1PU using one-pass KDF and CEK in the Direct Key Agreement mode"
            self.key_size = None
        else:
            self.name = f"ECDH-1PU+{key_wrapping.name}"
            self.description = f"ECDH-1PU using one-pass KDF and CEK wrapped with {key_wrapping.name}"
            self.key_size = key_wrapping.key_size
        self.key_wrapping = key_wrapping

    def _check_enc(self, enc: JWEEncModel) -> None:
        # https://datatracker.ietf.org/doc/html/draft-madden-jose-ecdh-1pu-04#section-2.1
        # The AES_CBC_HMAC_SHA2 algorithms described in section 5.2 of [RFC7518] are compactly
        # committing and can be used with ECDH-1PU in Key Agreement with Key Wrapping mode.
        # Other content encryption algorithms MUST be rejected.  In Direct Key Agreement
        # mode, any JWE content encryption algorithm MAY be used.
        if self.key_wrapping and not isinstance(enc, CBCHS2EncModel):
            description = (
                "In key agreement with key wrapping mode ECDH-1PU algorithm "
                "only supports AES_CBC_HMAC_SHA2 family encryption algorithms"
            )
            raise InvalidEncryptionAlgorithmError(description)

    def encrypt_agreed_upon_key(self, enc: JWEEncModel, recipient: Recipient[ECKey]) -> bytes:
        self._check_enc(enc)
        return self.__encrypt_agreed_upon_key(enc, recipient, None)

    def encrypt_agreed_upon_key_with_tag(self, enc: JWEEncModel, recipient: Recipient[ECKey], tag: bytes) -> bytes:
        self._check_enc(enc)
        return self.__encrypt_agreed_upon_key(enc, recipient, tag)

    def decrypt_agreed_upon_key(self, enc: JWEEncModel, recipient: Recipient[ECKey]) -> bytes:
        return self.__decrypt_agreed_upon_key(enc, recipient, None)

    def decrypt_agreed_upon_key_with_tag(self, enc: JWEEncModel, recipient: Recipient[ECKey], tag: bytes) -> bytes:
        return self.__decrypt_agreed_upon_key(enc, recipient, tag)

    def __encrypt_agreed_upon_key(self, enc: JWEEncModel, recipient: Recipient[ECKey], tag: bytes | None) -> bytes:
        sender_key = recipient.sender_key
        recipient_key = recipient.recipient_key
        ephemeral_key = recipient.ephemeral_key
        assert sender_key is not None
        assert recipient_key is not None
        assert ephemeral_key is not None

        sender_shared_key = sender_key.exchange_derive_key(recipient_key)
        ephemeral_shared_key = ephemeral_key.exchange_derive_key(recipient_key)
        shared_key = ephemeral_shared_key + sender_shared_key
        headers = recipient.headers()
        return derive_key_for_concat_kdf(shared_key, headers, enc.cek_size, self.key_size, tag)

    def __decrypt_agreed_upon_key(self, enc: JWEEncModel, recipient: Recipient[ECKey], tag: bytes | None) -> bytes:
        self._check_enc(enc)
        headers = recipient.headers()
        assert "epk" in headers

        sender_key = recipient.sender_key
        recipient_key = recipient.recipient_key
        assert sender_key is not None
        assert recipient_key is not None

        ephemeral_key = recipient_key.import_key(headers["epk"])
        sender_shared_key = recipient_key.exchange_derive_key(sender_key)
        ephemeral_shared_key = recipient_key.exchange_derive_key(ephemeral_key)
        shared_key = ephemeral_shared_key + sender_shared_key
        return derive_key_for_concat_kdf(shared_key, headers, enc.cek_size, self.key_size, tag)


JWE_ALG_MODELS = [
    ECDH1PUAlgModel(None),  # ECDH-1PU
    ECDH1PUAlgModel(A128KW),  # ECDH-1PU+A128KW
    ECDH1PUAlgModel(A192KW),  # ECDH-1PU+A192KW
    ECDH1PUAlgModel(A256KW),  # ECDH-1PU+A256KW
]


def register_ecdh_1pu() -> None:
    from ..jwe import JWERegistry
    from ..jwk import KeySet

    for model in JWE_ALG_MODELS:
        JWERegistry.register(model)
        KeySet.algorithm_keys[model.name] = model.key_types
