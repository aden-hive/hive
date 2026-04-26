from __future__ import annotations
import warnings
from typing import Any
from enum import Enum
from .model import JWSAlgModel
from ..errors import (
    JoseError,
    UnsupportedAlgorithmError,
    SecurityWarning,
    ExceededSizeError,
)
from ..registry import (
    JWS_HEADER_REGISTRY,
    Header,
    HeaderRegistryDict,
    check_registry_header,
    check_crit_header,
    check_supported_header,
)
from .._keys import KeySet

__all__ = [
    "JWSRegistry",
    "construct_registry",
    "default_registry",
]


class JWSRegistry:
    """A registry for JSON Web Signature to keep all the supported algorithms.
    An instance of ``JWSRegistry`` is usually used together with methods in
    ``joserfc.jws``.

    :param header_registry: extra header parameters registry
    :param algorithms: allowed algorithms to be used
    :param strict_check_header: only allow header key in the registry to be used
    """

    class Strategy(Enum):
        #: find the recommended algorithm
        RECOMMENDED = 1
        #: find the most secure algorithm
        SECURITY = 2

    default_header_registry: HeaderRegistryDict = JWS_HEADER_REGISTRY
    algorithms: dict[str, JWSAlgModel] = {}
    recommended: list[str] = []

    #: max header content's size in bytes
    max_header_length: int = 512
    #: max payload content's size in bytes
    max_payload_length: int = 8000
    #: max signature's size in bytes
    max_signature_length: int = 1024

    def __init__(
        self,
        header_registry: HeaderRegistryDict | None = None,
        algorithms: list[str] | None = None,
        strict_check_header: bool = True,
    ):
        self.header_registry: HeaderRegistryDict = {}
        self.header_registry.update(self.default_header_registry)
        if header_registry is not None:
            self.header_registry.update(header_registry)
        self.allowed = algorithms
        self.strict_check_header = strict_check_header

    @classmethod
    def register(cls, alg: JWSAlgModel) -> None:
        """Register a given JWS algorithm instance to the registry."""
        cls.algorithms[alg.name] = alg
        if alg.recommended:
            cls.recommended.append(alg.name)

    def get_alg(self, name: str) -> JWSAlgModel:
        """Get the allowed algorithm instance of the given name.

        :param name: value of the ``alg``, e.g. ``HS256``, ``RS256``
        """
        if name not in self.algorithms:
            raise UnsupportedAlgorithmError(f"Algorithm of '{name}' is not supported")

        if self.allowed:
            if name not in self.allowed:
                raise UnsupportedAlgorithmError(f"Algorithm of '{name}' is not allowed")
        else:
            if name not in self.recommended:
                raise UnsupportedAlgorithmError(f"Algorithm of '{name}' is not recommended")

        alg = self.algorithms[name]
        if alg.security_warning:
            warnings.warn(alg.security_warning, SecurityWarning)
        return alg

    def check_header(self, header: Header) -> None:
        """Check and validate the fields in header part of a JWS object."""
        check_crit_header(self.header_registry, header)
        check_registry_header(self.header_registry, header)
        if self.strict_check_header:
            check_supported_header(self.header_registry, header)

    def validate_header_size(self, header: bytes) -> None:
        if header and len(header) > self.max_header_length:
            raise ExceededSizeError(f"Header size exceeds {self.max_header_length} bytes.")

    def validate_payload_size(self, payload: bytes) -> None:
        if payload and len(payload) > self.max_payload_length:
            raise ExceededSizeError(f"Payload size exceeds {self.max_payload_length} bytes.")

    def validate_signature_size(self, signature: bytes) -> None:
        if len(signature) > self.max_signature_length:
            raise ExceededSizeError(f"Signature of exceeds {self.max_signature_length} bytes.")

    @classmethod
    def guess_algorithm(cls, key: Any, strategy: Strategy) -> JWSAlgModel | None:
        """Guess the JWS algorithm for a given key.

        :param key: key instance or a KeySet
        :param strategy: the strategy for guessing the JWS algorithm
        """
        if strategy == cls.Strategy.RECOMMENDED:
            algorithms = cls.filter_algorithms(key, cls.recommended)
        elif strategy == cls.Strategy.SECURITY:
            names = list(cls.algorithms.keys())
            algorithms = cls.filter_algorithms(key, names)
            # sort by security level
            algorithms.sort(key=lambda alg: alg.algorithm_security, reverse=True)
        else:
            raise NotImplementedError(f"Unknown algorithm strategy '{strategy}'")

        if algorithms:
            return algorithms[0]
        else:
            return None

    @classmethod
    def guess_alg(cls, key: Any, strategy: Strategy) -> str | None:  # pragma: no cover
        warnings.warn("Please use guess_algorithm(key, strategy)", DeprecationWarning)
        alg = cls.guess_algorithm(key, strategy)
        if alg:
            return alg.name
        return None

    @classmethod
    def filter_algorithms(cls, key: Any, names: list[str] | None = None) -> list[JWSAlgModel]:
        """Filter JWS algorithms based on the given algorithm names.

        :param key: a key instance or a KeySet
        :param names: list of algorithm names
        """
        if names is None:
            names = list(cls.algorithms.keys())
        rv: list[JWSAlgModel] = []
        if isinstance(key, KeySet):
            for k in key.keys:
                for alg in cls.filter_algorithms(k, names):
                    if alg not in rv:
                        rv.append(alg)
            return rv

        for name in names:
            alg = cls.algorithms[name]
            try:
                alg.check_key(key)
                rv.append(alg)
            except JoseError:
                pass
        return rv


#: default JWS registry
default_registry = JWSRegistry()


def construct_registry(algorithms: list[str] | None = None) -> JWSRegistry:
    if algorithms:
        registry = JWSRegistry(algorithms=algorithms)
    else:
        registry = default_registry
    return registry
