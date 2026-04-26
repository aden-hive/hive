from cryptography.hazmat.primitives.asymmetric.ec import SECP256K1
from .._rfc7518.ec_key import ECKey
from .._rfc7518.jws_algs import ESAlgorithm

ES256K = ESAlgorithm("ES256K", "secp256k1", 256)


def register_secp256k1() -> None:
    # https://tools.ietf.org/html/rfc8812#section-3.1
    ECKey.binding.register_curve("secp256k1", SECP256K1)


__all__ = ["ES256K", "register_secp256k1"]
