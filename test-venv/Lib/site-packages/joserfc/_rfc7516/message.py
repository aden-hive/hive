import secrets
import typing as t

from .models import (
    CompactEncryption,
    BaseJSONEncryption,
    GeneralJSONEncryption,
    FlattenedJSONEncryption,
    Recipient,
    JWEAlgModel,
    JWEEncModel,
    JWEKeyAgreement,
    JWEDirectEncryption,
    JWEKeyEncryption,
    JWEKeyWrapping,
)
from .registry import JWERegistry
from ..errors import (
    JoseError,
    DecodeError,
    InvalidEncryptedKeyError,
    InvalidExchangeKeyError,
    ConflictAlgorithmError,
)
from ..util import (
    json_b64encode,
    urlsafe_b64encode,
)

__all__ = [
    "EncryptionData",
    "perform_encrypt",
    "perform_decrypt",
]

EncryptionData = t.Union[CompactEncryption, GeneralJSONEncryption, FlattenedJSONEncryption]


def perform_encrypt(obj: EncryptionData, registry: JWERegistry) -> None:
    enc = registry.get_enc(obj.protected["enc"])
    cek, delayed_tasks = pre_encrypt_recipients(enc, obj.recipients, registry)

    # Step 9, Generate a random JWE Initialization Vector of the correct size
    # for the content encryption algorithm (if required for the algorithm);
    # otherwise, let the JWE Initialization Vector be the empty octet sequence.
    iv = enc.generate_iv()

    # Step 10, Compute the encoded Initialization Vector value
    # BASE64URL(JWE Initialization Vector).
    obj.base64_segments["iv"] = urlsafe_b64encode(iv)

    # Step 11, If a "zip" parameter was included, compress the plaintext using
    # the specified compression algorithm and let M be the octet sequence
    # representing the compressed plaintext; otherwise, let M be the octet
    # sequence representing the plaintext.
    assert obj.plaintext is not None

    plaintext: bytes
    if "zip" in obj.protected:
        zip_ = registry.get_zip(obj.protected["zip"])
        plaintext = zip_.compress(obj.plaintext)
    else:
        plaintext = obj.plaintext

    # Step 13, Compute the Encoded Protected Header value BASE64URL(UTF8(JWE Protected Header)).
    aad = json_b64encode(obj.protected)

    # Step 14, Let the Additional Authenticated Data encryption parameter be
    # ASCII(Encoded Protected Header).  However, if a JWE AAD value is
    # present (which can only be the case when using the JWE JSON Serialization),
    # instead let the Additional Authenticated Data encryption parameter be
    # ASCII(Encoded Protected Header || '.' || BASE64URL(JWE AAD)).
    if isinstance(obj, BaseJSONEncryption) and obj.aad:
        aad = aad + b"." + urlsafe_b64encode(obj.aad)
    obj.base64_segments["aad"] = aad

    # encrypting plaintext
    ciphertext, tag = enc.encrypt(plaintext, cek, iv, aad)

    # delay encrypting every recipient
    post_encrypt_recipients(enc, delayed_tasks, cek, tag)

    obj.base64_segments["ciphertext"] = urlsafe_b64encode(ciphertext)
    obj.base64_segments["tag"] = urlsafe_b64encode(tag)


def perform_decrypt(obj: EncryptionData, registry: JWERegistry) -> None:
    try:
        _perform_decrypt(obj, registry)
    except InvalidExchangeKeyError as error:
        raise DecodeError(error.description)


def _perform_decrypt(obj: EncryptionData, registry: JWERegistry) -> None:
    enc = registry.get_enc(obj.protected["enc"])

    iv = obj.bytes_segments["iv"]
    enc.check_iv(iv)

    tag = obj.bytes_segments["tag"]
    ciphertext = obj.bytes_segments["ciphertext"]

    cek_set = set()
    for recipient in obj.recipients:
        headers = recipient.headers()
        registry.check_header(headers, True)
        # Step 6, Determine the Key Management Mode employed by the algorithm
        # specified by the "alg" (algorithm) Header Parameter.
        alg = registry.get_alg(headers["alg"])
        try:
            cek = decrypt_recipient(alg, enc, recipient, tag)
            cek_set.add(cek)
        except (AssertionError, JoseError) as error:
            if registry.verify_all_recipients:
                raise error

    if not cek_set:
        raise DecodeError("Invalid recipients")

    if len(cek_set) > 1:  # pragma: no cover
        raise DecodeError("Multiple 'cek' found")

    cek = cek_set.pop()
    if len(cek) * 8 != enc.cek_size:  # pragma: no cover
        cek = secrets.token_bytes(enc.cek_size // 8)

    aad = json_b64encode(obj.protected)
    if isinstance(obj, BaseJSONEncryption) and obj.aad:
        aad = aad + b"." + urlsafe_b64encode(obj.aad)

    msg = enc.decrypt(ciphertext, tag, cek, iv, aad)
    if "zip" in obj.protected:
        zip_ = registry.get_zip(obj.protected["zip"])
        obj.plaintext = zip_.decompress(msg)
    else:
        obj.plaintext = msg


def pre_encrypt_recipients(
    enc: JWEEncModel, recipients: list[Recipient[t.Any]], registry: JWERegistry
) -> tuple[bytes, list[tuple[JWEKeyAgreement, Recipient[t.Any]]]]:
    cek: bytes = b""
    delayed_tasks: list[tuple[JWEKeyAgreement, Recipient[t.Any]]] = []
    for recipient in recipients:
        alg = __prepare_recipient_algorithm(recipient, registry)

        if alg.direct_mode:
            if len(recipients) > 1:
                raise ConflictAlgorithmError(f"Algorithm {alg.name} SHOULD have 1 recipient only")
            cek = __pre_encrypt_direct_mode(alg, enc, recipient)
        else:
            if not cek:
                # 2. When Key Wrapping, Key Encryption, or Key Agreement with Key
                # Wrapping are employed, generate a random CEK value.  See RFC
                # 4086 [RFC4086] for considerations on generating random values.
                # The CEK MUST have a length equal to that required for the
                # content encryption algorithm.
                cek = enc.generate_cek()

            if isinstance(alg, JWEKeyAgreement):
                delayed_tasks.append((alg, recipient))
            else:
                # 4. When Key Wrapping, or Key Encryption are employed, encrypt the CEK
                # to the recipient and let the result be the JWE Encrypted Key.
                assert isinstance(alg, (JWEKeyWrapping, JWEKeyEncryption))
                recipient.encrypted_key = alg.encrypt_cek(cek, recipient)
    return cek, delayed_tasks


def __prepare_recipient_algorithm(recipient: Recipient[t.Any], registry: JWERegistry) -> JWEAlgModel:
    headers = recipient.headers()
    registry.check_header(headers)
    # 1. Determine the Key Management Mode employed by the algorithm used
    # to determine the Content Encryption Key value.  (This is the
    # algorithm recorded in the "alg" (algorithm) Header Parameter of
    # the resulting JWE.)
    alg = registry.get_alg(headers["alg"])

    if isinstance(alg, JWEKeyAgreement):
        alg.prepare_ephemeral_key(recipient)
    return alg


def __pre_encrypt_direct_mode(alg: JWEAlgModel, enc: JWEEncModel, recipient: Recipient[t.Any]) -> bytes:
    cek: bytes
    if isinstance(alg, JWEKeyAgreement):
        # 3. When Direct Key Agreement is employed,
        # let the CEK be the agreed upon key.
        cek = alg.encrypt_agreed_upon_key(enc, recipient)
        if len(cek) * 8 != enc.cek_size:  # pragma: no cover
            cek = secrets.token_bytes(enc.cek_size // 8)
    else:
        # 6. When Direct Encryption is employed, let the CEK be the shared
        # symmetric key.
        assert isinstance(alg, JWEDirectEncryption)
        cek = alg.compute_cek(enc.cek_size, recipient)

    # 5. When Direct Key Agreement or Direct Encryption are employed, let
    # the JWE Encrypted Key be the empty octet sequence.
    recipient.encrypted_key = b""
    return cek


def post_encrypt_recipients(
    enc: JWEEncModel, tasks: list[tuple[JWEKeyAgreement, Recipient[t.Any]]], cek: bytes, tag: bytes
) -> None:
    for alg, recipient in tasks:
        if alg.tag_aware:
            agreed_upon_key = alg.encrypt_agreed_upon_key_with_tag(enc, recipient, tag)
        else:
            agreed_upon_key = alg.encrypt_agreed_upon_key(enc, recipient)
        # 4. When Key Agreement with Key Wrapping is employed, encrypt the CEK
        # to the recipient and let the result be the JWE Encrypted Key.
        recipient.encrypted_key = alg.wrap_cek_with_auk(cek, agreed_upon_key)


def decrypt_recipient(alg: JWEAlgModel, enc: JWEEncModel, recipient: Recipient[t.Any], tag: bytes) -> bytes:
    cek: bytes
    if alg.direct_mode:
        # 10.  When Direct Key Agreement or Direct Encryption are employed,
        # verify that the JWE Encrypted Key value is an empty octet
        # sequence.
        if recipient.encrypted_key:  # pragma: no cover
            raise InvalidEncryptedKeyError()

        if isinstance(alg, JWEKeyAgreement):
            # 8. When Direct Key Agreement is employed, let the CEK be the agreed upon key.
            cek = alg.decrypt_agreed_upon_key(enc, recipient)
        else:
            # 11. When Direct Encryption is employed, let the CEK be the shared
            # symmetric key.
            assert isinstance(alg, JWEDirectEncryption)
            cek = alg.compute_cek(enc.cek_size, recipient)
    elif isinstance(alg, JWEKeyAgreement):
        agreed_upon_key: bytes
        if alg.tag_aware:
            agreed_upon_key = alg.decrypt_agreed_upon_key_with_tag(enc, recipient, tag)
        else:
            agreed_upon_key = alg.decrypt_agreed_upon_key(enc, recipient)

        # 8. When Key Agreement with Key Wrapping is employed, the agreed upon key
        # will be used to decrypt the JWE Encrypted Key.
        assert recipient.encrypted_key is not None
        cek = alg.unwrap_cek_with_auk(recipient.encrypted_key, agreed_upon_key)
    else:
        # 9. When Key Wrapping, Key Encryption, or Key Agreement with Key
        # Wrapping are employed, decrypt the JWE Encrypted Key to produce
        # the CEK.  The CEK MUST have a length equal to that required for
        # the content encryption algorithm.  Note that when there are
        # multiple recipients, each recipient will only be able to decrypt
        # JWE Encrypted Key values that were encrypted to a key in that
        # recipient's possession.  It is therefore normal to only be able
        # to decrypt one of the per-recipient JWE Encrypted Key values to
        # obtain the CEK value.
        assert isinstance(alg, (JWEKeyWrapping, JWEKeyEncryption))
        cek = alg.decrypt_cek(recipient)
    return cek
