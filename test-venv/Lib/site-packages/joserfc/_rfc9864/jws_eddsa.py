import typing as t
from cryptography.exceptions import InvalidSignature
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PublicKey, Ed25519PrivateKey
from cryptography.hazmat.primitives.asymmetric.ed448 import Ed448PublicKey, Ed448PrivateKey
from ..errors import InvalidKeyCurveError
from .._rfc7515.model import JWSAlgModel
from .._rfc8037.okp_key import OKPKey


class EdDSAAlgorithm(JWSAlgModel):
    key_type = "OKP"

    def __init__(self, curve: t.Literal["Ed25519", "Ed448"]):
        self.name = curve
        self.curve = curve
        self.description = f"EdDSA using the {curve} parameter set"

    def check_key(self, key: OKPKey) -> None:
        super().check_key(key)
        if key.curve_name != self.curve:
            raise InvalidKeyCurveError(f"Key for '{self.name}' not supported, only '{self.curve}' allowed")

    def sign(self, msg: bytes, key: OKPKey) -> bytes:
        op_key = t.cast(t.Union[Ed25519PrivateKey, Ed448PrivateKey], key.get_op_key("sign"))
        return op_key.sign(msg)

    def verify(self, msg: bytes, sig: bytes, key: OKPKey) -> bool:
        op_key = t.cast(t.Union[Ed25519PublicKey, Ed448PublicKey], key.get_op_key("verify"))
        try:
            op_key.verify(sig, msg)
            return True
        except InvalidSignature:
            return False


Ed25519 = EdDSAAlgorithm("Ed25519")
Ed448 = EdDSAAlgorithm("Ed448")

JWS_ALGORITHMS: list[EdDSAAlgorithm] = [Ed25519, Ed448]
