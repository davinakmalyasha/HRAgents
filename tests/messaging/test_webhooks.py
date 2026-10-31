"""Webhook verification: authenticity, freshness, replay, and framing."""

from __future__ import annotations

import base64
import hashlib
import hmac

import pytest

from hr_agents.messaging.webhooks import (
    ReplayGuard,
    WebhookError,
    WebhookRefusal,
    WebhookScheme,
    verified_headers,
    verify_webhook,
)

SECRET = "whsec_" + base64.b64encode(b"0123456789abcdef0123456789abcdef").decode()
BODY = b'{"type":"email.received","data":{"id":"abc"}}'
NOW = 1_760_000_000.0


def svix_headers(delivery_id: str = "msg_1", *, timestamp: int = int(NOW)) -> dict[str, str]:
    return verified_headers(SECRET, delivery_id, BODY, timestamp=timestamp)


def test_a_correct_svix_delivery_is_accepted() -> None:
    verdict = verify_webhook(
        scheme=WebhookScheme.SVIX,
        headers=svix_headers(),
        body=BODY,
        secret=SECRET,
        now=NOW,
    )
    assert verdict.delivery_id == "msg_1"
    assert verdict.scheme is WebhookScheme.SVIX
    assert verdict.timestamp == int(NOW)


def test_header_lookup_is_case_insensitive() -> None:
    headers = {name.upper(): value for name, value in svix_headers().items()}
    assert (
        verify_webhook(
            scheme=WebhookScheme.SVIX, headers=headers, body=BODY, secret=SECRET, now=NOW
        ).delivery_id
        == "msg_1"
    )


def test_a_tampered_body_is_refused() -> None:
    with pytest.raises(WebhookError) as caught:
        verify_webhook(
            scheme=WebhookScheme.SVIX,
            headers=svix_headers(),
            body=BODY + b" ",
            secret=SECRET,
            now=NOW,
        )
    assert caught.value.refusal is WebhookRefusal.BAD_SIGNATURE


def test_a_wrong_secret_is_refused() -> None:
    other = "whsec_" + base64.b64encode(b"ffffffffffffffffffffffffffffffff").decode()
    with pytest.raises(WebhookError) as caught:
        verify_webhook(
            scheme=WebhookScheme.SVIX,
            headers=svix_headers(),
            body=BODY,
            secret=other,
            now=NOW,
        )
    assert caught.value.refusal is WebhookRefusal.BAD_SIGNATURE


def test_a_stale_delivery_is_refused() -> None:
    with pytest.raises(WebhookError) as caught:
        verify_webhook(
            scheme=WebhookScheme.SVIX,
            headers=svix_headers(timestamp=int(NOW) - 3600),
            body=BODY,
            secret=SECRET,
            now=NOW,
        )
    assert caught.value.refusal is WebhookRefusal.STALE_TIMESTAMP


def test_a_future_delivery_beyond_tolerance_is_refused() -> None:
    with pytest.raises(WebhookError) as caught:
        verify_webhook(
            scheme=WebhookScheme.SVIX,
            headers=svix_headers(timestamp=int(NOW) + 3600),
            body=BODY,
            secret=SECRET,
            now=NOW,
        )
    assert caught.value.refusal is WebhookRefusal.STALE_TIMESTAMP


@pytest.mark.parametrize("missing", ["svix-id", "svix-timestamp", "svix-signature"])
def test_every_required_header_is_required(missing: str) -> None:
    headers = svix_headers()
    headers.pop(missing)
    with pytest.raises(WebhookError) as caught:
        verify_webhook(
            scheme=WebhookScheme.SVIX, headers=headers, body=BODY, secret=SECRET, now=NOW
        )
    assert caught.value.refusal is WebhookRefusal.MISSING_HEADERS


def test_multiple_signature_versions_accept_any_v1_match() -> None:
    headers = svix_headers()
    headers["svix-signature"] = "v2,deadbeef " + headers["svix-signature"]
    assert (
        verify_webhook(
            scheme=WebhookScheme.SVIX, headers=headers, body=BODY, secret=SECRET, now=NOW
        ).delivery_id
        == "msg_1"
    )


def test_a_non_v1_signature_only_is_refused() -> None:
    headers = svix_headers()
    headers["svix-signature"] = "v2,deadbeef"
    with pytest.raises(WebhookError) as caught:
        verify_webhook(
            scheme=WebhookScheme.SVIX, headers=headers, body=BODY, secret=SECRET, now=NOW
        )
    assert caught.value.refusal is WebhookRefusal.BAD_SIGNATURE


def test_a_malformed_secret_is_refused_not_crashed() -> None:
    with pytest.raises(WebhookError) as caught:
        verify_webhook(
            scheme=WebhookScheme.SVIX,
            headers=svix_headers(),
            body=BODY,
            secret="not-base64!!",
            now=NOW,
        )
    assert caught.value.refusal is WebhookRefusal.INVALID_SECRET


def test_a_replayed_delivery_is_refused_once_seen() -> None:
    guard = ReplayGuard()
    headers = svix_headers()
    verify_webhook(
        scheme=WebhookScheme.SVIX, headers=headers, body=BODY, secret=SECRET, guard=guard, now=NOW
    )
    with pytest.raises(WebhookError) as caught:
        verify_webhook(
            scheme=WebhookScheme.SVIX,
            headers=headers,
            body=BODY,
            secret=SECRET,
            guard=guard,
            now=NOW,
        )
    assert caught.value.refusal is WebhookRefusal.REPLAYED


def test_replay_window_expires_so_a_retry_after_the_window_is_accepted() -> None:
    clock = [1000.0]
    guard = ReplayGuard(window_seconds=60, _now=lambda: clock[0])
    assert guard.claim("svix:msg_1") is True
    assert guard.claim("svix:msg_1") is False
    clock[0] += 61
    assert guard.claim("svix:msg_1") is True


def test_the_replay_guard_is_bounded() -> None:
    clock = [0.0]
    guard = ReplayGuard(window_seconds=10_000, max_keys=3, _now=lambda: clock[0])
    for index in range(5):
        clock[0] += 1
        guard.claim(f"k{index}")
    assert guard.tracked <= 3


META_HEADERS = {
    "X-Hub-Signature-256": "sha256=" + hmac.new(b"app-secret", BODY, hashlib.sha256).hexdigest(),
    "X-Hub-Delivery-Id": "delivery-1",
}


def test_a_correct_meta_delivery_is_accepted() -> None:
    verdict = verify_webhook(
        scheme=WebhookScheme.META,
        headers=META_HEADERS,
        body=BODY,
        secret="app-secret",
        now=NOW,
    )
    assert verdict.delivery_id == "delivery-1"


def test_meta_rejects_a_bad_signature() -> None:
    headers = dict(META_HEADERS)
    headers["X-Hub-Signature-256"] = "sha256=" + "0" * 64
    with pytest.raises(WebhookError) as caught:
        verify_webhook(
            scheme=WebhookScheme.META, headers=headers, body=BODY, secret="app-secret", now=NOW
        )
    assert caught.value.refusal is WebhookRefusal.BAD_SIGNATURE


def test_meta_requires_a_delivery_id_for_the_replay_guard() -> None:
    headers = dict(META_HEADERS)
    headers.pop("X-Hub-Delivery-Id")
    with pytest.raises(WebhookError) as caught:
        verify_webhook(
            scheme=WebhookScheme.META, headers=headers, body=BODY, secret="app-secret", now=NOW
        )
    assert caught.value.refusal is WebhookRefusal.MISSING_HEADERS


def test_meta_replays_are_refused() -> None:
    guard = ReplayGuard()
    verify_webhook(
        scheme=WebhookScheme.META,
        headers=META_HEADERS,
        body=BODY,
        secret="app-secret",
        guard=guard,
        now=NOW,
    )
    with pytest.raises(WebhookError) as caught:
        verify_webhook(
            scheme=WebhookScheme.META,
            headers=META_HEADERS,
            body=BODY,
            secret="app-secret",
            guard=guard,
            now=NOW,
        )
    assert caught.value.refusal is WebhookRefusal.REPLAYED


def test_the_secret_is_never_echoed_in_the_refusal() -> None:
    with pytest.raises(WebhookError) as caught:
        verify_webhook(
            scheme=WebhookScheme.SVIX,
            headers=svix_headers(),
            body=BODY + b"x",
            secret=SECRET,
            now=NOW,
        )
    message = str(caught.value)
    assert "whsec_" not in message
    assert SECRET not in message
