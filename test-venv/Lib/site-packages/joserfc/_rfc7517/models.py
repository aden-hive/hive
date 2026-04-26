from __future__ import annotations
import typing as t
from collections.abc import KeysView
from abc import ABCMeta, abstractmethod
from .types import DictKey, AnyKey, KeyParameters
from .._rfc7638 import calculate_thumbprint
from .._rfc9278 import concat_thumbprint_uri
from ..registry import (
    KeyParameterRegistryDict,
    JWK_PARAMETER_REGISTRY,
    KeyOperationRegistryDict,
    JWK_OPERATION_REGISTRY,
)
from ..util import to_bytes
from ..errors import (
    KeyParameterError,
    UnsupportedKeyUseError,
    UnsupportedKeyAlgorithmError,
    UnsupportedKeyOperationError,
)


NativePrivateKey = t.TypeVar("NativePrivateKey")
NativePublicKey = t.TypeVar("NativePublicKey")
GenericKey = t.TypeVar("GenericKey", bound="BaseKey[t.Any, t.Any]")


class NativeKeyBinding(metaclass=ABCMeta):
    use_key_ops_registry: t.ClassVar[dict[str, list[str]]] = {
        "sig": ["sign", "verify"],
        "enc": ["encrypt", "decrypt", "wrapKey", "unwrapKey", "deriveKey", "deriveBits"],
    }

    @classmethod
    @abstractmethod
    def convert_raw_key_to_dict(cls, raw_key: t.Any, private: bool) -> DictKey:
        pass

    @classmethod
    @abstractmethod
    def import_from_dict(cls, value: DictKey) -> t.Any:
        pass

    @classmethod
    @abstractmethod
    def import_from_bytes(cls, value: bytes, password: t.Any = None) -> t.Any:
        pass

    @staticmethod
    def as_bytes(
        key: GenericKey,
        encoding: t.Literal["PEM", "DER"] | None = None,
        private: bool | None = None,
        password: str | None = None,
    ) -> bytes:
        raise NotImplementedError()

    @classmethod
    def validate_dict_key_registry(cls, dict_key: DictKey, registry: KeyParameterRegistryDict) -> None:
        for k in registry:
            if registry[k].required and k not in dict_key:
                raise KeyParameterError(f"'{k}' is required")

            if k in dict_key:
                try:
                    registry[k].validate(dict_key[k])
                except ValueError as error:
                    raise KeyParameterError(f"'{k}' {error}")

    @classmethod
    def validate_dict_key_use_operations(cls, dict_key: DictKey) -> None:
        if "use" in dict_key and "key_ops" in dict_key:
            _use: str = dict_key["use"]  # type: ignore
            operations = cls.use_key_ops_registry[_use]
            for op in dict_key["key_ops"]:
                if op not in operations:
                    raise KeyParameterError("'use' and 'key_ops' does not match")


class BaseKey(t.Generic[NativePrivateKey, NativePublicKey], metaclass=ABCMeta):
    key_type: t.ClassVar[str]
    binding: t.ClassVar[t.Type[NativeKeyBinding]]
    value_registry: t.ClassVar[KeyParameterRegistryDict]
    param_registry: t.ClassVar[KeyParameterRegistryDict] = JWK_PARAMETER_REGISTRY
    operation_registry: t.ClassVar[KeyOperationRegistryDict] = JWK_OPERATION_REGISTRY
    thumbprint_digest_method: t.Literal["sha256", "sha384", "sha512"] = "sha256"

    def __init__(
        self,
        raw_value: NativePrivateKey | NativePublicKey,
        original_value: t.Any,
        parameters: KeyParameters | None = None,
    ):
        self._raw_value = raw_value
        self.original_value = original_value
        self.extra_parameters = parameters
        self._dict_value: DictKey = {}
        if isinstance(original_value, dict):
            if parameters is not None:
                data = {**original_value, **parameters, "kty": self.key_type}
            else:
                data = {**original_value, "kty": self.key_type}
            self.validate_dict_key(data)
            self._dict_value = data

    def __eq__(self, other: t.Any) -> bool:
        if not isinstance(other, self.__class__):
            return False
        return self.dict_value == other.dict_value

    def keys(self) -> KeysView[str]:
        return self.dict_value.keys()

    def __getitem__(self, k: str) -> str | list[str]:
        return self.dict_value[k]

    def get(self, k: str, default: str | list[str] | None = None) -> str | list[str] | None:
        return self.dict_value.get(k, default)

    def ensure_kid(self) -> None:
        """Ensure this key has a ``kid``. If ``kid`` is not provided by default,
        it will generate the kid with ``.thumbprint`` method, which is defined
        by RFC7638."""
        if "kid" not in self.dict_value:
            self._dict_value["kid"] = self.thumbprint()

    @property
    def kid(self) -> str | None:
        """The "kid" value of the JSON Web Key."""
        return t.cast(t.Optional[str], self.get("kid"))

    @property
    def alg(self) -> str | None:
        """The "alg" value of the JSON Web Key."""
        return t.cast(t.Optional[str], self.get("alg"))

    @property
    def raw_value(self) -> t.Any:
        raise NotImplementedError()

    @property
    def is_private(self) -> bool:
        raise NotImplementedError()

    @property
    def dict_value(self) -> DictKey:
        """Property of the Key in Dict (JSON)."""
        if self._dict_value:
            return self._dict_value

        data = self.binding.convert_raw_key_to_dict(self.raw_value, self.is_private)
        if self.extra_parameters is not None:
            data.update(self.extra_parameters)  # type: ignore
        data["kty"] = self.key_type
        self.validate_dict_key(data)
        self._dict_value = data
        return data

    @property
    def public_key(self) -> NativePublicKey:
        raise NotImplementedError()

    @property
    def private_key(self) -> NativePrivateKey | None:
        raise NotImplementedError()

    def thumbprint(self) -> str:
        """Call this method will generate the thumbprint with algorithm
        defined in RFC7638."""
        fields = [k for k in self.value_registry if self.value_registry[k].required]
        fields.append("kty")
        data = {key: self.dict_value[key] for key in fields}
        return calculate_thumbprint(data, self.thumbprint_digest_method)

    def thumbprint_uri(self) -> str:
        """Call this method will generate the thumbprint URI
        defined in RFC9278."""
        value = self.thumbprint()
        return concat_thumbprint_uri(value, self.thumbprint_digest_method)

    def as_dict(self, private: bool | None = None, **params: t.Any) -> DictKey:
        """Output this key to a JWK format (in dict). By default, it will return
        the ``dict_value`` of this key.

        :param private: determine whether this method should output private key or not
        :param params: other parameters added into this key
        :raise: ValueError
        """
        # check private conflicts
        if private and not self.is_private:
            raise ValueError("This key is not a private key.")

        data = self.dict_value.copy()
        if private is not False:
            data.update(params)
            return data

        # clear private fields
        for k in self.dict_value:
            if k in self.value_registry and self.value_registry[k].private:
                del data[k]

        data.update(params)
        return data

    def check_use(self, use: str) -> None:
        """Check if this key supports the given "use".

        Values defined by this specification are:

        - "sig" (signature)
        - "enc" (encryption)

        Other values MAY be used.  The "use" value is a case-sensitive
        string. Use of the "use" member is OPTIONAL, unless the application
        requires its presence.

        :param use: this key is used for, e.g. "sig", "enc"
        :raise UnsupportedKeyUseError: if this key is not designed for the given use
        """
        designed_use = self.get("use")
        if designed_use and designed_use != use:
            raise UnsupportedKeyUseError(f"This key is designed to be used for '{designed_use}'")

    def check_alg(self, alg: str) -> None:
        """Check if this key supports the given "alg".

        :param alg: the algorithm this key is intended to be used, e.g. "HS256", "ECDH-EC"
        :raise UnsupportedKeyAlgorithmError: if this key is not designed for the given algorithm
        """
        designed_alg = self.get("alg")
        if designed_alg and designed_alg != alg:
            raise UnsupportedKeyAlgorithmError(f"This key is designed for algorithm '{designed_alg}'")

    def check_key_op(self, operation: str) -> None:
        """Check if the given key_op is supported by this key.

        :param operation: key operation value, such as "sign", "encrypt".
        :raise UnsupportedKeyOperationError: if the operation is not supported by this key.
        """
        key_ops = self.get("key_ops")
        if key_ops is not None and operation not in key_ops:
            raise UnsupportedKeyOperationError(f"Unsupported key_op '{operation}'")

        assert operation in self.operation_registry
        reg = self.operation_registry[operation]
        if reg.private and not self.is_private:
            raise UnsupportedKeyOperationError(f"Invalid key_op '{operation}' for public key")

    @t.overload
    def get_op_key(self, operation: t.Literal["verify", "encrypt", "wrapKey", "deriveKey"]) -> NativePublicKey: ...

    @t.overload
    def get_op_key(self, operation: t.Literal["sign", "decrypt", "unwrapKey"]) -> NativePrivateKey: ...

    def get_op_key(self, operation: str) -> NativePublicKey | NativePrivateKey:
        self.check_key_op(operation)
        reg = self.operation_registry[operation]
        if reg.private:
            assert self.private_key is not None
            return self.private_key
        return self.public_key

    @classmethod
    def validate_dict_key(cls, data: DictKey) -> None:
        cls.binding.validate_dict_key_registry(data, cls.param_registry)
        cls.binding.validate_dict_key_registry(data, cls.value_registry)
        cls.binding.validate_dict_key_use_operations(data)

    @classmethod
    def import_key(
        cls: t.Type[GenericKey],
        value: AnyKey,
        parameters: KeyParameters | None = None,
        password: t.Any = None,
    ) -> GenericKey:
        if isinstance(value, dict):
            cls.validate_dict_key(value)
            raw_key = cls.binding.import_from_dict(value)
            return cls(raw_key, value, parameters)

        raw_key = cls.binding.import_from_bytes(to_bytes(value), password)
        return cls(raw_key, value, parameters)

    @classmethod
    def generate_key(
        cls: t.Type[GenericKey],
        *,
        parameters: KeyParameters | None = None,
        private: bool = True,
        auto_kid: bool = False,
    ) -> GenericKey:
        raise NotImplementedError()


class SymmetricKey(BaseKey[bytes, bytes], metaclass=ABCMeta):
    @property
    def raw_value(self) -> bytes:
        """The raw key in bytes."""
        return self._raw_value

    @property
    def is_private(self) -> bool:
        """A symmetric key will always be private."""
        return True

    @property
    def public_key(self) -> bytes:
        """Returns the ``raw_value`` as the public key."""
        return self.raw_value

    @property
    def private_key(self) -> bytes:
        """Returns the ``raw_value`` as the private key."""
        return self.raw_value


class AsymmetricKey(BaseKey[NativePrivateKey, NativePublicKey], metaclass=ABCMeta):
    @property
    def raw_value(self) -> t.Union[NativePublicKey, NativePrivateKey]:
        return self._raw_value

    def as_bytes(
        self,
        encoding: t.Literal["PEM", "DER"] | None = None,
        private: bool | None = None,
        password: str | None = None,
    ) -> bytes:
        return self.binding.as_bytes(self, encoding, private, password)

    def as_pem(self, private: bool | None = None, password: str | None = None) -> bytes:
        return self.as_bytes(private=private, password=password)

    def as_der(self, private: bool | None = None, password: str | None = None) -> bytes:
        return self.as_bytes(encoding="DER", private=private, password=password)


class CurveKey(AsymmetricKey[NativePrivateKey, NativePublicKey]):
    @property
    @abstractmethod
    def curve_name(self) -> str:
        pass

    @abstractmethod
    def exchange_derive_key(self, key: t.Any) -> bytes:
        pass
