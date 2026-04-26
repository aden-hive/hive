from cryptography.exceptions import InvalidSignature
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PublicKey, Ed25519PrivateKey
from cryptography.hazmat.primitives.asymmetric.ed448 import Ed448PublicKey, Ed448PrivateKey
from ..errors import InvalidKeyTypeError
from .._rfc7515.model import JWSAlgModel
from .okp_key import OKPKey


class EdDSAAlgorithm(JWSAlgModel):
    name = "EdDSA"
    description = "Edwards-curve Digital Signature Algorithm for JWS"
    key_type = "OKP"
    security_warning = "EdDSA is deprecated via RFC 9864"

    def sign(self, msg: bytes, key: OKPKey) -> bytes:
        op_key = key.get_op_key("sign")
        if not isinstance(op_key, (Ed25519PrivateKey, Ed448PrivateKey)):
            raise InvalidKeyTypeError(f"Algorithm '{self.name}' requires 'Ed25519' or 'Ed448' OKP key")
        return op_key.sign(msg)

    def verify(self, msg: bytes, sig: bytes, key: OKPKey) -> bool:
        op_key = key.get_op_key("verify")
        if not isinstance(op_key, (Ed25519PublicKey, Ed448PublicKey)):
            raise InvalidKeyTypeError(f"Algorithm '{self.name}' requires 'Ed25519' or 'Ed448' OKP key")
        try:
            op_key.verify(sig, msg)
            return True
        except InvalidSignature:
            return False


EdDSA = EdDSAAlgorithm()

# compatible
EdDSAAlgModel = EdDSAAlgorithm
