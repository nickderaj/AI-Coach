"""Web Push: RFC 8291 encryption, RFC 8292 signatures, and sending (no sockets)."""

import base64
import io
import json
import logging
import urllib.error
import urllib.request
import urllib.response
from collections.abc import Mapping
from datetime import UTC, datetime
from email.message import Message

import pytest
from cryptography.exceptions import InvalidSignature
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import ec
from cryptography.hazmat.primitives.asymmetric.utils import encode_dss_signature

from trainer.services.notices import PushOutcome, decode_key
from trainer.services.webpush import (
    MAX_PAYLOAD,
    TIMEOUT_S,
    TOKEN_LIFETIME,
    TTL_S,
    UrllibTransport,
    VapidKey,
    WebPushSender,
    b64url,
    encrypt,
    push_opener,
    vapid_authorization,
)
from trainer.storage.notices import Subscription

BUILD_OPENER = urllib.request.build_opener


def joined(text: str) -> bytes:
    """Decode the RFC's base64url, which it wraps with spaces."""
    return decode_key("".join(text.split()))


# RFC 8291, section 5 and appendix A.
PLAINTEXT = joined("V2hlbiBJIGdyb3cgdXAsIEkgd2FudCB0byBiZSBhIHdhdGVybWVsb24")
AS_PRIVATE = joined("yfWPiYE-n46HLnH0KqZOF1fJJU3MYrct3AELtAQ-oRw")
UA_PUBLIC = joined(
    "BCVxsr7N_eNgVRqvHtD0zTZsEc6-VV-JvLexhqUzORcx aOzi6-AYWXvTBHm4bjyPjs7Vd8pZGH6SRpkNtoIAiw4"
)
SALT = joined("DGv6ra1nlYgDCS1FRnbzlw")
AUTH = joined("BTBZMqHH6r4Tts7J_aSIgg")
RESULT = joined(
    """
    DGv6ra1nlYgDCS1FRnbzlwAAEABBBP4z9KsN6nGRTbVYI_c7VJSPQTBtkgcy27ml
    mlMoZIIgDll6e3vCYLocInmYWAmS6TlzAC8wEqKK6PBru3jl7A_yl95bQpu6cVPT
    pK4Mqgkf1CXztLVBSt2Ks3oZwbuwXPXLWyouBWLVWGNWQexSgSxsj_Qulcy4a-fN
    """
)
NOW = datetime(2026, 10, 2, 9, 0, tzinfo=UTC)
APPLE = "https://web.push.apple.com/QGuT8ar"
CONTACT = "mailto:owner@example.com"


def server_key() -> ec.EllipticCurvePrivateKey:
    return ec.derive_private_key(int.from_bytes(AS_PRIVATE), ec.SECP256R1())


def test_b64url_is_unpadded_and_url_safe() -> None:
    assert b64url(b"\xfb\xff") == "-_8"
    assert b64url(b"") == ""
    assert b64url(b"\x00\x00\x17") == "AAAX"  # only padding is stripped


# ---------------------------------------------------------------- encryption


def test_encryption_matches_the_rfc_example() -> None:
    assert encrypt(PLAINTEXT, UA_PUBLIC, AUTH, server_key(), SALT) == RESULT


def test_the_header_names_the_record_size_and_the_servers_key() -> None:
    body = encrypt(PLAINTEXT, UA_PUBLIC, AUTH, server_key(), SALT)

    assert body[:16] == SALT
    assert int.from_bytes(body[16:20]) == 4096
    assert body[20] == 65
    assert body[21:86] == joined(
        "BP4z9KsN6nGRTbVYI_c7VJSPQTBtkgcy27mlmlMoZIIgDll6e3vCYLocInmYWAmS6TlzAC8wEqKK6PBru3jl7A8"
    )


def test_the_longest_payload_fits_one_record() -> None:
    body = encrypt(bytes(MAX_PAYLOAD), UA_PUBLIC, AUTH, server_key(), SALT)

    assert MAX_PAYLOAD == 4096 - 16 - 1
    assert len(body) == 86 + 4096


def test_a_longer_payload_is_refused() -> None:
    with pytest.raises(ValueError, match=r"^a push carries at most 4079 bytes$"):
        encrypt(bytes(MAX_PAYLOAD + 1), UA_PUBLIC, AUTH, server_key(), SALT)


def test_a_browser_key_off_the_curve_is_refused() -> None:
    with pytest.raises(ValueError, match="Invalid EC key"):
        encrypt(PLAINTEXT, b"\x04" + bytes(64), AUTH, server_key(), SALT)


# ---------------------------------------------------------------- VAPID


def test_a_vapid_key_round_trips_through_its_text() -> None:
    key = VapidKey.generate()

    again = VapidKey.from_text(key.text)

    assert again.text == key.text
    assert again.public_text == key.public_text
    assert len(decode_key(key.text)) == 32
    public = decode_key(key.public_text)
    assert (len(public), public[0]) == (65, 4)


def test_a_vapid_key_from_known_bytes() -> None:
    key = VapidKey.from_text(b64url(AS_PRIVATE))

    assert key.public_text == (
        "BP4z9KsN6nGRTbVYI_c7VJSPQTBtkgcy27mlmlMoZIIgDll6e3vCYLocInmYWAmS6TlzAC8wEqKK6PBru3jl7A8"
    )
    # A private key with leading zero bytes keeps all 32 of them.
    small = VapidKey.from_text(b64url(bytes(31) + b"\x07"))
    assert decode_key(small.text) == bytes(31) + b"\x07"


@pytest.mark.parametrize("text", [b64url(bytes(30) + b"\x01"), b64url(bytes(33))])
def test_a_vapid_key_must_be_32_bytes(text: str) -> None:
    with pytest.raises(ValueError, match=r"^a VAPID private key is 32 bytes of base64url$"):
        VapidKey.from_text(text)


def test_a_vapid_key_must_be_base64url() -> None:
    with pytest.raises(ValueError, match=r"^not base64url$"):
        VapidKey.from_text("!")


def parse_authorization(header: str) -> tuple[str, str]:
    scheme, _, rest = header.partition(" ")
    assert scheme == "vapid"
    token, key = rest.split(", ")
    assert token.startswith("t=")
    assert key.startswith("k=")
    return token[2:], key[2:]


def test_the_authorization_is_a_signed_token_and_the_public_key() -> None:
    key = VapidKey.from_text(b64url(AS_PRIVATE))

    token, public = parse_authorization(vapid_authorization(APPLE + "/more?x=1", key, CONTACT, NOW))

    assert public == key.public_text
    header, claims, signature = token.split(".")
    assert json.loads(decode_key(header)) == {"typ": "JWT", "alg": "ES256"}
    assert json.loads(decode_key(claims)) == {
        "aud": "https://web.push.apple.com",
        "exp": int(NOW.timestamp()) + 12 * 60 * 60,
        "sub": CONTACT,
    }
    assert TOKEN_LIFETIME.total_seconds() == 12 * 60 * 60
    assert "=" not in token
    assert " " not in token
    raw = decode_key(signature)
    assert len(raw) == 64
    der = encode_dss_signature(int.from_bytes(raw[:32]), int.from_bytes(raw[32:]))
    verifier = ec.EllipticCurvePublicKey.from_encoded_point(ec.SECP256R1(), decode_key(public))
    verifier.verify(der, f"{header}.{claims}".encode(), ec.ECDSA(hashes.SHA256()))
    with pytest.raises(InvalidSignature):
        verifier.verify(der, f"{header}.{claims}x".encode(), ec.ECDSA(hashes.SHA256()))


def test_the_token_is_compact_json() -> None:
    token, _ = parse_authorization(vapid_authorization(APPLE, VapidKey.generate(), CONTACT, NOW))

    header, claims, _ = token.split(".")
    assert decode_key(header) == b'{"typ":"JWT","alg":"ES256"}'
    assert decode_key(claims).startswith(b'{"aud":"https://web.push.apple.com","exp":')


# ---------------------------------------------------------------- the transport


class FakeResponse(urllib.response.addinfourl):
    """A response as urllib's handlers expect one (they read ``msg``)."""

    msg = "fake"


class FakePushService(urllib.request.BaseHandler):
    """Answers https:// requests with a fixed status; records each request."""

    handler_order = 10  # before urllib's own proxy and HTTPS handlers

    def __init__(self, status: int | Exception, location: str | None = None) -> None:
        """Answer every request with ``status``, or raise it."""
        self.status = status
        self.location = location
        self.requests: list[urllib.request.Request] = []
        self.timeouts: list[float | None] = []

    def https_open(self, request: urllib.request.Request) -> urllib.response.addinfourl:
        self.requests.append(request)
        self.timeouts.append(request.timeout)
        if isinstance(self.status, Exception):
            raise self.status
        headers = Message()
        if self.location:
            headers["Location"] = self.location
        return FakeResponse(io.BytesIO(b"{}"), headers, request.full_url, self.status)


def transport(fake: FakePushService) -> UrllibTransport:
    return UrllibTransport(push_opener(fake))


def test_the_transport_posts_and_answers_the_status() -> None:
    fake = FakePushService(201)

    status = transport(fake).post(APPLE, {"TTL": "60", "Urgency": "normal"}, b"body")

    assert status == 201
    (request,) = fake.requests
    assert request.full_url == APPLE
    assert request.get_method() == "POST"
    assert request.data == b"body"
    assert request.get_header("Ttl") == "60"
    assert request.get_header("Urgency") == "normal"
    assert fake.timeouts == [TIMEOUT_S] == [10.0]


@pytest.mark.parametrize("status", [400, 403, 404, 410, 413, 429, 500])
def test_the_transport_answers_an_error_status(status: int) -> None:
    assert transport(FakePushService(status)).post(APPLE, {}, b"") == status


@pytest.mark.parametrize("status", [301, 302, 303, 307, 308])
def test_the_transport_does_not_follow_redirects(status: int) -> None:
    # urllib would follow a 301, 302 or 303 of a POST as a GET.
    fake = FakePushService(status, location="https://elsewhere.example.com/x")

    assert transport(fake).post(APPLE, {}, b"") == status
    assert [request.full_url for request in fake.requests] == [APPLE]


def test_urllib_alone_would_follow_a_redirect() -> None:
    fake = FakePushService(302, location="https://elsewhere.example.com/x")

    with pytest.raises(urllib.error.HTTPError):
        urllib.request.build_opener(fake).open(APPLE, data=b"", timeout=1)

    assert len(fake.requests) > 1


class AfterProxies(FakePushService):
    """Answers after any proxy handler (order 100) has had the request."""

    handler_order = 200


def test_the_push_opener_ignores_proxy_settings(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("https_proxy", "http://proxy.example.com:3128")
    fake = AfterProxies(201)

    assert UrllibTransport(push_opener(fake)).post(APPLE, {}, b"") == 201

    (request,) = fake.requests
    assert request.host == "web.push.apple.com"  # a proxy handler would have set its own


def test_a_proxy_handler_would_have_been_seen(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("https_proxy", "http://proxy.example.com:3128")
    fake = AfterProxies(201)

    urllib.request.build_opener(fake).open(APPLE, timeout=1)

    assert fake.requests[0].host == "proxy.example.com:3128"


def test_the_default_transport_sends_through_the_push_opener(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    fake = FakePushService(302, location="https://elsewhere.example.com/x")

    def build(*handlers: urllib.request.BaseHandler) -> urllib.request.OpenerDirector:
        return BUILD_OPENER(*handlers, fake)

    monkeypatch.setattr(urllib.request, "build_opener", build)

    assert UrllibTransport().post(APPLE, {}, b"") == 302  # the redirect was not followed
    assert fake.timeouts == [TIMEOUT_S]


def test_the_transport_raises_when_nothing_answers() -> None:
    fake = FakePushService(urllib.error.URLError("no route"))

    with pytest.raises(OSError, match="no route"):
        transport(fake).post(APPLE, {}, b"")


# ---------------------------------------------------------------- sending


class FakeTransport:
    """Records each POST and answers ``status``, or raises it."""

    def __init__(self, status: int | OSError = 201) -> None:
        """Answer every POST with ``status``."""
        self.status = status
        self.posts: list[tuple[str, dict[str, str], bytes]] = []

    def post(self, url: str, headers: Mapping[str, str], body: bytes) -> int:
        self.posts.append((url, dict(headers), body))
        if isinstance(self.status, OSError):
            raise self.status
        return self.status


def browser() -> tuple[ec.EllipticCurvePrivateKey, Subscription]:
    private = ec.generate_private_key(ec.SECP256R1())
    public = b64url(
        private.public_key().public_bytes(
            serialization.Encoding.X962, serialization.PublicFormat.UncompressedPoint
        )
    )
    return private, Subscription(APPLE, public, b64url(AUTH))


def sender(fake: FakeTransport) -> WebPushSender:
    return WebPushSender(
        VapidKey.from_text(b64url(AS_PRIVATE)),
        CONTACT,
        fake,
        clock=lambda: NOW,
        fresh=lambda: (server_key(), SALT),
    )


def test_a_push_is_encrypted_signed_and_sent() -> None:
    fake = FakeTransport(201)
    subscription = Subscription(APPLE, b64url(UA_PUBLIC), b64url(AUTH) + "==")

    assert sender(fake).send(subscription, PLAINTEXT) is PushOutcome.DELIVERED

    ((url, headers, body),) = fake.posts
    assert url == APPLE
    assert body == RESULT
    assert headers == {
        "Authorization": headers["Authorization"],
        "Content-Encoding": "aes128gcm",
        "Content-Type": "application/octet-stream",
        "TTL": "86400",
        "Urgency": "normal",
    }
    assert TTL_S == 86400
    token, public = parse_authorization(headers["Authorization"])
    assert public == VapidKey.from_text(b64url(AS_PRIVATE)).public_text
    claims = json.loads(decode_key(token.split(".")[1]))
    assert claims == {
        "aud": "https://web.push.apple.com",
        "exp": int(NOW.timestamp()) + 12 * 60 * 60,
        "sub": CONTACT,
    }


def test_each_push_uses_a_fresh_key_and_salt_by_default() -> None:
    fake = FakeTransport(201)
    _, subscription = browser()
    plain = WebPushSender(VapidKey.generate(), CONTACT, fake)

    plain.send(subscription, b"one")
    plain.send(subscription, b"one")

    first, second = (body for _, _, body in fake.posts)
    assert first[:16] != second[:16]  # the salt
    assert first[21:86] != second[21:86]  # the one-off key
    claims = json.loads(
        decode_key(parse_authorization(fake.posts[0][1]["Authorization"])[0].split(".")[1])
    )
    assert abs(claims["exp"] - (datetime.now(UTC) + TOKEN_LIFETIME).timestamp()) < 60


@pytest.mark.parametrize(
    ("status", "outcome"),
    [
        (200, PushOutcome.DELIVERED),
        (201, PushOutcome.DELIVERED),
        (202, PushOutcome.DELIVERED),
        (299, PushOutcome.DELIVERED),
        (199, PushOutcome.FAILED),
        (300, PushOutcome.FAILED),
        (307, PushOutcome.FAILED),
        (400, PushOutcome.FAILED),
        (403, PushOutcome.FAILED),
        (404, PushOutcome.GONE),
        (410, PushOutcome.GONE),
        (413, PushOutcome.FAILED),
        (429, PushOutcome.FAILED),
        (500, PushOutcome.FAILED),
    ],
)
def test_the_push_services_answer_decides_the_outcome(status: int, outcome: PushOutcome) -> None:
    _, subscription = browser()

    assert sender(FakeTransport(status)).send(subscription, b"x") is outcome


def test_an_unreachable_push_service_is_a_failure(caplog: pytest.LogCaptureFixture) -> None:
    _, subscription = browser()

    with caplog.at_level(logging.WARNING):
        outcome = sender(FakeTransport(OSError("timed out"))).send(subscription, b"x")

    assert outcome is PushOutcome.FAILED
    assert caplog.messages == ["push: web.push.apple.com is unreachable: timed out"]


def test_a_refusal_is_logged_by_host_only(caplog: pytest.LogCaptureFixture) -> None:
    _, subscription = browser()

    with caplog.at_level(logging.INFO):
        sender(FakeTransport(403)).send(subscription, b"x")
        sender(FakeTransport(410)).send(subscription, b"x")

    assert caplog.messages == [
        "push: web.push.apple.com refused a push (403)",
        "push: a subscription at web.push.apple.com has ended (410)",
    ]


def test_a_push_to_anything_but_a_push_service_is_never_sent(
    caplog: pytest.LogCaptureFixture,
) -> None:
    fake = FakeTransport(201)
    _, subscription = browser()
    elsewhere = Subscription("https://127.0.0.1/api", subscription.p256dh, subscription.auth)

    with caplog.at_level(logging.WARNING):
        assert sender(fake).send(elsewhere, b"x") is PushOutcome.FAILED

    assert fake.posts == []
    assert caplog.messages == ["push: refused to send to 127.0.0.1: not a push service"]


@pytest.mark.parametrize(
    ("keys", "reason"),
    [
        ({"p256dh": base64.urlsafe_b64encode(b"\x04" + bytes(64)).decode()}, "Invalid EC key."),
        ({"auth": "!"}, "not base64url"),
    ],
)
def test_a_subscription_with_bad_keys_is_a_failure(
    keys: dict[str, str], reason: str, caplog: pytest.LogCaptureFixture
) -> None:
    fake = FakeTransport(201)
    _, good = browser()
    bad = Subscription(APPLE, keys.get("p256dh", good.p256dh), keys.get("auth", good.auth))

    with caplog.at_level(logging.WARNING):
        assert sender(fake).send(bad, b"x") is PushOutcome.FAILED

    assert fake.posts == []
    assert caplog.messages == [f"push: could not encrypt for web.push.apple.com: {reason}"]


def test_a_payload_too_long_is_a_failure() -> None:
    fake = FakeTransport(201)
    _, subscription = browser()

    assert sender(fake).send(subscription, bytes(MAX_PAYLOAD + 1)) is PushOutcome.FAILED
    assert fake.posts == []
