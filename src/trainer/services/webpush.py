"""Web Push: send one push to a browser through its push service.

The payload is encrypted for the browser (RFC 8291, ``aes128gcm``), so the push
service cannot read it. Each request is signed with the server's VAPID key
(RFC 8292), so the push service knows which server is sending.
"""

from __future__ import annotations

import base64
import json
import logging
import os
import urllib.error
import urllib.request
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from http import HTTPStatus
from typing import TYPE_CHECKING, Protocol, override
from urllib.parse import urlsplit

from cryptography.hazmat.primitives import hashes, hmac, serialization
from cryptography.hazmat.primitives.asymmetric import ec
from cryptography.hazmat.primitives.asymmetric.utils import decode_dss_signature
from cryptography.hazmat.primitives.ciphers.aead import AESGCM

from trainer.services.notices import PushOutcome, decode_key, is_push_endpoint

if TYPE_CHECKING:
    from collections.abc import Callable, Mapping

    from trainer.storage.notices import Subscription

logger = logging.getLogger(__name__)

# One record holds the whole payload: the browser's limit, less the AES-GCM tag
# and the padding delimiter, is the most a push can carry.
RECORD_SIZE = 4096
TAG_LENGTH = 16
MAX_PAYLOAD = RECORD_SIZE - TAG_LENGTH - 1
SALT_LENGTH = 16
KEY_LENGTH = 32  # a P-256 private key, or one coordinate of a public key
# How long a push service keeps a push for a phone that is off or out of signal.
TTL_S = 24 * 60 * 60
# How long a VAPID signature is good for; RFC 8292 allows at most a day.
TOKEN_LIFETIME = timedelta(hours=12)
TIMEOUT_S = 10.0
CURVE = ec.SECP256R1()


def b64url(data: bytes) -> str:
    """``data`` as unpadded base64url, the form Web Push uses throughout."""
    return base64.urlsafe_b64encode(data).decode().rstrip("=")


def _hmac(key: bytes, data: bytes) -> bytes:
    mac = hmac.HMAC(key, hashes.SHA256())
    mac.update(data)
    return mac.finalize()


def _hkdf(salt: bytes, secret: bytes, info: bytes, length: int | None = None) -> bytes:
    """HKDF-SHA-256 (RFC 5869), one block (32 bytes) or ``length`` bytes of it.

    One block is all Web Push needs.
    """
    return _hmac(_hmac(salt, secret), info + b"\x01")[:length]


def _point(key: ec.EllipticCurvePublicKey) -> bytes:
    return key.public_bytes(
        serialization.Encoding.X962, serialization.PublicFormat.UncompressedPoint
    )


def encrypt(
    plaintext: bytes,
    browser_key: bytes,
    auth: bytes,
    server_key: ec.EllipticCurvePrivateKey,
    salt: bytes,
) -> bytes:
    """The ``aes128gcm`` body of a push of ``plaintext`` (RFC 8291, section 3).

    ``browser_key`` and ``auth`` are the subscription's keys; ``server_key`` is
    a fresh key pair and ``salt`` fresh random bytes, for this push alone.

    Raises:
        ValueError: if ``plaintext`` is too long for one record, or
            ``browser_key`` is not a P-256 point.
    """
    if len(plaintext) > MAX_PAYLOAD:
        message = f"a push carries at most {MAX_PAYLOAD} bytes"
        raise ValueError(message)
    server_public = _point(server_key.public_key())
    secret = server_key.exchange(
        ec.ECDH(), ec.EllipticCurvePublicKey.from_encoded_point(CURVE, browser_key)
    )
    ikm = _hkdf(auth, secret, b"WebPush: info\x00" + browser_key + server_public)
    content_key = _hkdf(salt, ikm, b"Content-Encoding: aes128gcm\x00", 16)
    nonce = _hkdf(salt, ikm, b"Content-Encoding: nonce\x00", 12)
    header = salt + RECORD_SIZE.to_bytes(4) + bytes([len(server_public)]) + server_public
    # A single record ends with the delimiter 0x02, and is not padded.
    return header + AESGCM(content_key).encrypt(nonce, plaintext + b"\x02", None)


@dataclass(frozen=True)
class VapidKey:
    """The server's VAPID key pair (P-256), which signs every push request."""

    private: ec.EllipticCurvePrivateKey

    @classmethod
    def generate(cls) -> VapidKey:
        """A new random key pair."""
        return cls(ec.generate_private_key(CURVE))

    @classmethod
    def from_text(cls, text: str) -> VapidKey:
        """The key pair of a private key written by :attr:`text`.

        Raises:
            ValueError: if ``text`` is not a base64url P-256 private key.
        """
        raw = decode_key(text)
        if len(raw) != KEY_LENGTH:
            message = "a VAPID private key is 32 bytes of base64url"
            raise ValueError(message)
        return cls(ec.derive_private_key(int.from_bytes(raw), CURVE))

    @property
    def text(self) -> str:
        """The private key, as base64url of its 32 bytes."""
        return b64url(self.private.private_numbers().private_value.to_bytes(KEY_LENGTH))

    @property
    def public_text(self) -> str:
        """The public key, as browsers take it: base64url of the uncompressed point."""
        return b64url(_point(self.private.public_key()))


def vapid_authorization(endpoint: str, key: VapidKey, contact: str, now: datetime) -> str:
    """The ``Authorization`` header of a push to ``endpoint`` (RFC 8292, section 3).

    The token names the push service's origin, expires after
    ``TOKEN_LIFETIME``, and gives ``contact`` (a ``mailto:`` or ``https:``
    address) so the push service can reach the sender.
    """
    parts = urlsplit(endpoint)
    claims = {
        "aud": f"{parts.scheme}://{parts.netloc}",
        "exp": int((now + TOKEN_LIFETIME).timestamp()),
        "sub": contact,
    }
    signed = ".".join(
        b64url(json.dumps(part, separators=(",", ":")).encode())
        for part in ({"typ": "JWT", "alg": "ES256"}, claims)
    )
    r, s = decode_dss_signature(key.private.sign(signed.encode(), ec.ECDSA(hashes.SHA256())))
    signature = b64url(r.to_bytes(KEY_LENGTH) + s.to_bytes(KEY_LENGTH))
    return f"vapid t={signed}.{signature}, k={key.public_text}"


class Transport(Protocol):
    """Sends one HTTP POST and answers its status."""

    def post(self, url: str, headers: Mapping[str, str], body: bytes) -> int:
        """POST ``body`` to ``url``; the response's status.

        Raises:
            OSError: if no response came.
        """
        ...


class _NoRedirects(urllib.request.HTTPRedirectHandler):
    """A push service never redirects: a redirect is answered as the refusal it is."""

    @override
    def redirect_request(self, *_args: object, **_kwargs: object) -> None:
        return None


def push_opener(*handlers: urllib.request.BaseHandler) -> urllib.request.OpenerDirector:
    """An opener that ignores proxy settings and follows no redirects (plus ``handlers``)."""
    return urllib.request.build_opener(urllib.request.ProxyHandler({}), _NoRedirects(), *handlers)


class UrllibTransport:
    """POSTs with the standard library: no proxies, no redirects, a short timeout."""

    def __init__(
        self, opener: urllib.request.OpenerDirector | None = None, timeout: float = TIMEOUT_S
    ) -> None:
        """Send through ``opener``, by default :func:`push_opener`'s."""
        self._opener = opener or push_opener()
        self._timeout = timeout

    def post(self, url: str, headers: Mapping[str, str], body: bytes) -> int:
        """POST ``body`` to ``url``; the response's status, an error's included.

        A request with a body is a POST.
        """
        request = urllib.request.Request(  # noqa: S310  # why: the sender checks every URL is HTTPS on a push service first
            url, data=body, headers=dict(headers)
        )
        try:
            with self._opener.open(request, timeout=self._timeout) as response:
                status: int = response.status
        except urllib.error.HTTPError as error:
            error.close()
            return error.code
        return status


class WebPushSender:
    """Encrypts, signs and sends pushes; one ``send`` per push (``PushSender``)."""

    def __init__(  # why: the clock and random sources are injected for tests
        self,
        key: VapidKey,
        contact: str,
        transport: Transport | None = None,
        *,
        clock: Callable[[], datetime] = lambda: datetime.now(UTC),
        fresh: Callable[[], tuple[ec.EllipticCurvePrivateKey, bytes]] | None = None,
    ) -> None:
        """Sign as ``key`` with ``contact``, and send through ``transport``.

        ``fresh`` makes each push's one-off key pair and salt.
        """
        self._key = key
        self._contact = contact
        self._transport = transport or UrllibTransport()
        self._clock = clock
        self._fresh = fresh or _fresh

    def send(self, subscription: Subscription, payload: bytes) -> PushOutcome:
        """Push ``payload`` to ``subscription``; never raises."""
        endpoint = subscription.endpoint
        host = urlsplit(endpoint).hostname
        if not is_push_endpoint(endpoint):
            logger.warning("push: refused to send to %s: not a push service", host)
            return PushOutcome.FAILED
        try:
            body = encrypt(
                payload,
                decode_key(subscription.p256dh),
                decode_key(subscription.auth),
                *self._fresh(),
            )
        except ValueError as error:
            logger.warning("push: could not encrypt for %s: %s", host, error)
            return PushOutcome.FAILED
        headers = {
            "Authorization": vapid_authorization(endpoint, self._key, self._contact, self._clock()),
            "Content-Encoding": "aes128gcm",
            "Content-Type": "application/octet-stream",
            "TTL": str(TTL_S),
            "Urgency": "normal",
        }
        try:
            status = self._transport.post(endpoint, headers, body)
        except OSError as error:
            logger.warning("push: %s is unreachable: %s", host, error)
            return PushOutcome.FAILED
        return _outcome(status, host)


def _fresh() -> tuple[ec.EllipticCurvePrivateKey, bytes]:
    return ec.generate_private_key(CURVE), os.urandom(SALT_LENGTH)


def _outcome(status: int, host: str | None) -> PushOutcome:
    if HTTPStatus.OK <= status < HTTPStatus.MULTIPLE_CHOICES:
        return PushOutcome.DELIVERED
    if status in {HTTPStatus.NOT_FOUND, HTTPStatus.GONE}:
        logger.info("push: a subscription at %s has ended (%s)", host, status)
        return PushOutcome.GONE
    logger.warning("push: %s refused a push (%s)", host, status)
    return PushOutcome.FAILED
