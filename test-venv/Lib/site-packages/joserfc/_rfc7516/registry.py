from __future__ import annotations
import warnings
import typing as t
from .models import JWEAlgModel, JWEEncModel, JWEZipModel
from ..errors import (
    UnsupportedAlgorithmError,
    SecurityWarning,
    ExceededSizeError,
)
from ..registry import (
    Header,
    HeaderRegistryDict,
    JWE_HEADER_REGISTRY,
    check_supported_header,
    check_registry_header,
    check_crit_header,
)

__all__ = [
    "JWEAlgorithm",
    "JWERegistry",
    "default_registry",
]

JWEAlgorithm = t.Union[JWEAlgModel, JWEEncModel, JWEZipModel]

AlgorithmsDict = t.TypedDict(
    "AlgorithmsDict",
    {
        "alg": dict[str, JWEAlgModel],
        "enc": dict[str, JWEEncModel],
        "zip": dict[str, JWEZipModel],
    },
)


class JWERegistry:
    """A registry for JSON Web Encryption to keep all the supported algorithms.
    An instance of ``JWERegistry`` is usually used together with methods in
    ``joserfc.jwe``.

    :param header_registry: extra header parameters registry
    :param algorithms: allowed algorithms to be used
    :param verify_all_recipients: validating all recipients in a JSON serialization
    :param strict_check_header: only allow header key in the registry to be used
    """

    algorithms: AlgorithmsDict = {
        "alg": {},
        "enc": {},
        "zip": {},
    }
    recommended: t.ClassVar[list[str]] = []

    #: max protected header content's size in bytes
    max_protected_header_length: int = 1024
    #: max encrypted key's size in bytes
    max_encrypted_key_length: int = 1024
    #: max initialization vector's size in bytes
    max_initialization_vector_length: int = 64
    #: max ciphertext's size in bytes
    max_ciphertext_length: int = 65536  # 64KB
    #: max auth tag's size in bytes
    max_auth_tag_length: int = 64

    def __init__(
        self,
        header_registry: HeaderRegistryDict | None = None,
        algorithms: list[str] | None = None,
        verify_all_recipients: bool = True,
        strict_check_header: bool = True,
    ):
        self.header_registry: HeaderRegistryDict = {}
        self.header_registry.update(JWE_HEADER_REGISTRY)
        if header_registry is not None:
            self.header_registry.update(header_registry)
        self.allowed = algorithms
        self.verify_all_recipients = verify_all_recipients
        self.strict_check_header = strict_check_header

    @classmethod
    def register(cls, model: JWEAlgorithm) -> None:
        cls.algorithms[model.algorithm_location][model.name] = model  # type: ignore
        if model.recommended:
            cls.recommended.append(model.name)

    def check_header(self, header: Header, check_more: bool = False) -> None:
        """Check and validate the fields in header part of a JWS object."""
        check_crit_header(self.header_registry, header)
        check_registry_header(self.header_registry, header)

        alg = self.get_alg(header["alg"])
        if alg.more_header_registry:
            check_registry_header(alg.more_header_registry, header, check_more)

            if self.strict_check_header:
                allowed_registry = self.header_registry.copy()
                allowed_registry.update(alg.more_header_registry)
                check_supported_header(allowed_registry, header)
        elif self.strict_check_header:
            check_supported_header(self.header_registry, header)

    def validate_protected_header_size(self, header: bytes) -> None:
        if header and len(header) > self.max_protected_header_length:
            raise ExceededSizeError(f"Header size exceeds {self.max_protected_header_length} bytes.")

    def validate_encrypted_key_size(self, ek: bytes) -> None:
        if ek and len(ek) > self.max_encrypted_key_length:
            raise ExceededSizeError(f"Encrypted key size exceeds {self.max_encrypted_key_length} bytes.")

    def validate_initialization_vector_size(self, iv: bytes) -> None:
        if iv and len(iv) > self.max_initialization_vector_length:
            raise ExceededSizeError(
                f"Initialization vector size exceeds {self.max_initialization_vector_length} bytes."
            )

    def validate_ciphertext_size(self, ciphertext: bytes) -> None:
        if ciphertext and len(ciphertext) > self.max_ciphertext_length:
            raise ExceededSizeError(f"Ciphertext size exceeds {self.max_ciphertext_length} bytes.")

    def validate_auth_tag_size(self, tag: bytes) -> None:
        if tag and len(tag) > self.max_auth_tag_length:
            raise ExceededSizeError(f"Auth tag size exceeds {self.max_auth_tag_length} bytes.")

    def get_alg(self, name: str) -> JWEAlgModel:
        """Get the allowed ("alg") algorithm instance of the given name.

        :param name: value of the ``alg``, e.g. ``ECDH-ES``, ``A128KW``
        """
        registry = self.algorithms["alg"]
        self._check_algorithm(name, registry)
        alg: JWEAlgModel = registry[name]
        if alg.security_warning:
            warnings.warn(alg.security_warning, SecurityWarning)
        return alg

    def get_enc(self, name: str) -> JWEEncModel:
        """Get the allowed ("enc") algorithm instance of the given name.

        :param name: value of the ``enc``, e.g. ``A128CBC-HS256``, ``A128GCM``
        """
        registry = self.algorithms["enc"]
        self._check_algorithm(name, registry)
        return registry[name]

    def get_zip(self, name: str) -> JWEZipModel:
        """Get the allowed ("zip") algorithm instance of the given name.

        :param name: value of the ``zip``, e.g. ``DEF``
        """
        registry = self.algorithms["zip"]
        self._check_algorithm(name, registry)
        return registry[name]

    def _check_algorithm(self, name: str, registry: dict[str, t.Any]) -> None:
        if name not in registry:
            raise UnsupportedAlgorithmError(f"Algorithm of '{name}' is not supported")

        if self.allowed:
            if name not in self.allowed:
                raise UnsupportedAlgorithmError(f"Algorithm of '{name}' is not allowed")
        else:
            if name not in self.recommended:
                raise UnsupportedAlgorithmError(f"Algorithm of '{name}' is not recommended")


default_registry = JWERegistry()
