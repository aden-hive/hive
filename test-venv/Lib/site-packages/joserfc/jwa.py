from ._rfc7515.registry import JWSRegistry
from ._rfc7515.model import JWSAlgModel
from ._rfc7516.registry import JWERegistry
from ._rfc7516.models import (
    JWEDirectEncryption,
    JWEKeyEncryption,
    JWEKeyWrapping,
    JWEKeyAgreement,
    JWEAlgModel,
    JWEEncModel,
    JWEZipModel,
)
from ._rfc7518.jws_algs import (
    NoneAlgorithm,
    HMACAlgorithm,
    RSAAlgorithm,
    ESAlgorithm,
    RSAPSSAlgorithm,
    JWS_ALGORITHMS as RFC7518_JWS_ALGORITHMS,
)
from ._rfc7518.jwe_algs import (
    DirectAlgEncryption,
    AESAlgKeyWrapping,
    ECDHESAlgKeyAgreement,
    AESGCMAlgKeyWrapping,
    PBES2HSAlgKeyEncryption,
    JWE_ALG_MODELS,
)
from ._rfc7518.jwe_encs import (
    CBCHS2EncModel,
    GCMEncModel,
    JWE_ENC_MODELS,
)
from ._rfc7518.jwe_zips import (
    DeflateZipModel,
    JWE_ZIP_MODELS,
)
from ._rfc8037.jws_eddsa import EdDSA, EdDSAAlgorithm
from ._rfc8812 import ES256K
from ._rfc9864 import JWS_ALGORITHMS as RFC9864_JWS_ALGORITHMS
from ._keys import KeySet

__all__ = [
    # JWS algorithms
    "JWS_ALGORITHMS",
    "JWSAlgModel",
    "NoneAlgorithm",
    "HMACAlgorithm",
    "RSAAlgorithm",
    "ESAlgorithm",
    "RSAPSSAlgorithm",
    "EdDSAAlgorithm",
    # JWE algorithms
    "JWE_ALG_MODELS",
    "JWE_ENC_MODELS",
    "JWE_ZIP_MODELS",
    "JWEAlgModel",
    "JWEDirectEncryption",
    "JWEKeyEncryption",
    "JWEKeyWrapping",
    "JWEKeyAgreement",
    "DirectAlgEncryption",
    "AESAlgKeyWrapping",
    "ECDHESAlgKeyAgreement",
    "AESGCMAlgKeyWrapping",
    "PBES2HSAlgKeyEncryption",
    "JWEEncModel",
    "CBCHS2EncModel",
    "GCMEncModel",
    "JWEZipModel",
    "DeflateZipModel",
    # setup methods
    "setup_jws_algorithms",
    "setup_jwe_algorithms",
]

JWS_ALGORITHMS = [
    *RFC7518_JWS_ALGORITHMS,
    EdDSA,
    ES256K,
    *RFC9864_JWS_ALGORITHMS,
]


def setup_jws_algorithms() -> None:
    for _alg in JWS_ALGORITHMS:
        JWSRegistry.register(_alg)
        KeySet.algorithm_keys[_alg.name] = [_alg.key_type]


def setup_jwe_algorithms() -> None:
    for _alg in JWE_ALG_MODELS:
        KeySet.algorithm_keys[_alg.name] = _alg.key_types
        JWERegistry.register(_alg)

    for _enc in JWE_ENC_MODELS:
        JWERegistry.register(_enc)

    for _zip in JWE_ZIP_MODELS:
        JWERegistry.register(_zip)
