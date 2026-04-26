"""
joserfc._rfc7518
~~~~~~~~~~~~~~~~

Originally designed in ``authlib.jose.rfc7518``.

"alg" (Algorithm) Header Parameter Values for JWS per `Section 3`_.

.. _`Section 3`: https://tools.ietf.org/html/rfc7518#section-3
"""

import hmac
import hashlib
import typing as t
from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.asymmetric.utils import (
    decode_dss_signature,
    encode_dss_signature,
)
from cryptography.hazmat.primitives.asymmetric.ec import ECDSA
from cryptography.hazmat.primitives.asymmetric import padding
from cryptography.exceptions import InvalidSignature
from .._rfc7515.model import JWSAlgModel
from ..errors import InvalidKeyCurveError
from .oct_key import OctKey
from .rsa_key import RSAKey
from .ec_key import ECKey
from .util import encode_int, decode_int


class NoneAlgorithm(JWSAlgModel):
    name = "none"
    description = "No digital signature or MAC performed"
    security_warning = 'JWS algorithm "none" is deprecated, via draft-ietf-jose-deprecate-none-rsa15-02'

    def sign(self, msg: bytes, key: t.Any) -> bytes:
        return b""

    def verify(self, msg: bytes, sig: bytes, key: t.Any) -> bool:
        return sig == b""


class HMACAlgorithm(JWSAlgModel):
    """HMAC using SHA algorithms for JWS. Available algorithms:

    - HS256: HMAC using SHA-256
    - HS384: HMAC using SHA-384
    - HS512: HMAC using SHA-512
    """

    SHA256 = hashlib.sha256
    SHA384 = hashlib.sha384
    SHA512 = hashlib.sha512

    def __init__(self, sha_type: t.Literal[256, 384, 512], recommended: bool = False):
        self.name = f"HS{sha_type}"
        self.description = f"HMAC using SHA-{sha_type}"
        self.recommended = recommended
        self.hash_alg = getattr(self, f"SHA{sha_type}")
        self.algorithm_security = sha_type

    def sign(self, msg: bytes, key: OctKey) -> bytes:
        # it is faster than the one in cryptography
        op_key = key.get_op_key("sign")
        return hmac.new(op_key, msg, self.hash_alg).digest()

    def verify(self, msg: bytes, sig: bytes, key: OctKey) -> bool:
        op_key = key.get_op_key("verify")
        v_sig = hmac.new(op_key, msg, self.hash_alg).digest()
        return hmac.compare_digest(sig, v_sig)


class _RSAAlgModel(JWSAlgModel):
    key_type = "RSA"

    SHA256 = hashes.SHA256
    SHA384 = hashes.SHA384
    SHA512 = hashes.SHA512
    padding: padding.AsymmetricPadding

    def __init__(self, sha_type: t.Literal[256, 384, 512], recommended: bool = False):
        self.recommended = recommended
        self.hash_alg = getattr(self, f"SHA{sha_type}")
        self.algorithm_security = sha_type

    def sign(self, msg: bytes, key: RSAKey) -> bytes:
        op_key = key.get_op_key("sign")
        return op_key.sign(msg, self.padding, self.hash_alg())

    def verify(self, msg: bytes, sig: bytes, key: RSAKey) -> bool:
        op_key = key.get_op_key("verify")
        try:
            op_key.verify(sig, msg, self.padding, self.hash_alg())
            return True
        except InvalidSignature:
            return False


class RSAAlgorithm(_RSAAlgModel):
    """RSA using SHA algorithms for JWS. Available algorithms:

    - RS256: RSASSA-PKCS1-v1_5 using SHA-256
    - RS384: RSASSA-PKCS1-v1_5 using SHA-384
    - RS512: RSASSA-PKCS1-v1_5 using SHA-512
    """

    padding = padding.PKCS1v15()

    def __init__(self, sha_type: t.Literal[256, 384, 512], recommended: bool = False):
        super().__init__(sha_type, recommended)
        self.name = f"RS{sha_type}"
        self.description = f"RSASSA-PKCS1-v1_5 using SHA-{sha_type}"


class ESAlgorithm(JWSAlgModel):
    """ECDSA using SHA algorithms for JWS. Available algorithms:

    - ES256: ECDSA using P-256 and SHA-256
    - ES384: ECDSA using P-384 and SHA-384
    - ES512: ECDSA using P-521 and SHA-512
    """

    key_type = "EC"

    SHA256 = hashes.SHA256
    SHA384 = hashes.SHA384
    SHA512 = hashes.SHA512

    def __init__(self, name: str, curve: str, sha_type: t.Literal[256, 384, 512], recommended: bool = False):
        self.name = name
        self.curve = curve
        self.description = f"ECDSA using {self.curve} and SHA-{sha_type}"
        self.recommended = recommended
        self.hash_alg = getattr(self, f"SHA{sha_type}")
        self.algorithm_security = sha_type

    def check_key(self, key: ECKey) -> None:
        super().check_key(key)
        if key.curve_name != self.curve:
            raise InvalidKeyCurveError(f"Key for '{self.name}' not supported, only '{self.curve}' allowed")

    def sign(self, msg: bytes, key: ECKey) -> bytes:
        op_key = key.get_op_key("sign")
        der_sig = op_key.sign(msg, ECDSA(self.hash_alg()))
        r, s = decode_dss_signature(der_sig)
        size = key.curve_key_size
        return encode_int(r, size) + encode_int(s, size)

    def verify(self, msg: bytes, sig: bytes, key: ECKey) -> bool:
        key_size = key.curve_key_size
        length = (key_size + 7) // 8

        if len(sig) != 2 * length:
            return False

        r = decode_int(sig[:length])
        s = decode_int(sig[length:])
        der_sig = encode_dss_signature(r, s)

        try:
            op_key = key.get_op_key("verify")
            op_key.verify(der_sig, msg, ECDSA(self.hash_alg()))
            return True
        except InvalidSignature:
            return False


class RSAPSSAlgorithm(_RSAAlgModel):
    """RSASSA-PSS using SHA algorithms for JWS. Available algorithms:

    - PS256: RSASSA-PSS using SHA-256 and MGF1 with SHA-256
    - PS384: RSASSA-PSS using SHA-384 and MGF1 with SHA-384
    - PS512: RSASSA-PSS using SHA-512 and MGF1 with SHA-512
    """

    def __init__(self, sha_type: t.Literal[256, 384, 512]):
        super().__init__(sha_type, False)
        self.name = f"PS{sha_type}"
        self.description = f"RSASSA-PSS using SHA-{sha_type} and MGF1 with SHA-{sha_type}"
        self.padding = padding.PSS(mgf=padding.MGF1(self.hash_alg()), salt_length=self.hash_alg.digest_size)


JWS_ALGORITHMS: list[JWSAlgModel] = [
    NoneAlgorithm(),  # none
    HMACAlgorithm(256, True),  # HS256
    HMACAlgorithm(384),  # HS384
    HMACAlgorithm(512),  # HS512
    RSAAlgorithm(256, True),  # RS256
    RSAAlgorithm(384),  # RS384
    RSAAlgorithm(512),  # RS512
    ESAlgorithm("ES256", "P-256", 256, True),
    ESAlgorithm("ES384", "P-384", 384),
    ESAlgorithm("ES512", "P-521", 512),
    RSAPSSAlgorithm(256),  # PS256
    RSAPSSAlgorithm(384),  # PS384
    RSAPSSAlgorithm(512),  # PS512
]

# compatible
NoneAlgModel = NoneAlgorithm
HMACAlgModel = HMACAlgorithm
RSAAlgModel = RSAAlgorithm
ECAlgModel = ESAlgorithm
RSAPSSAlgModel = RSAPSSAlgorithm
