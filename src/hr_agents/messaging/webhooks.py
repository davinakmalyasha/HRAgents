"""Webhook authenticity: HMAC verification plus a bounded replay guard.

An inbound webhook is an unauthenticated public endpoint that mutates candidate
records, so two properties must hold before its payload is read:

1. **Authenticity** — the body was signed by the provider that claims to have
   sent it. Compared in constant time, over the *raw* bytes: re-serialising the
   parsed JSON changes key order and whitespace and produces a different digest.
2. **Freshness** — the request was sent recently and has not been seen before.
   A valid signature is replayable forever otherwise, and the provider's
   signature covers the timestamp, not the fact that we already acted on it.

Schemes differ only in framing:

- **Svix / Resend** — ``svix-id``, ``svix-timestamp``, ``svix-signature`` with
  space-separated ``v1,<base64>`` versions; the signed content is
  ``{id}.{timestamp}.{body}`` and the key is base64 with a ``whsec_`` prefix.
- **Meta / WhatsApp** — ``X-Hub-Signature-256`` as ``sha256=<hex>`` over the raw
  body; authenticity only, so the replay guard keys on the delivery id the
  payload carries.

A missing header, an unknown scheme and a good-but-old signature are all
refusals, and they are refused *before* the body is handed to a service. The
replay guard is in-process and bounded: it stops a duplicate delivery retrying
within the window, not a distributed attacker with a stolen signature, which is
what the timestamp tolerance is for.
"""

from __future__ import annotations

import base64
import hashlib
import hmac
import time
from collections.abc import Callable, Mapping
from dataclasses import dataclass, field
from enum import StrEnum

from pydantic import Field

from hr_agents.models import StrictModel


class WebhookScheme(StrEnum):
    """How a provider frames its signature."""

    SVIX = "svix"
    META = "meta"


class WebhookRefusal(StrEnum):
    """Why a webhook was refused, named so the response can say which."""

    MISSING_HEADERS = "missing_headers"
    UNKNOWN_SCHEME = "unknown_scheme"
    INVALID_SECRET = "invalid_secret"
    BAD_SIGNATURE = "bad_signature"
    STALE_TIMESTAMP = "stale_timestamp"
    REPLAYED = "replayed"


class WebhookError(RuntimeError):
    """The request is not an authentic, fresh provider delivery."""

    def __init__(self, refusal: WebhookRefusal, detail: str) -> None:
        super().__init__(detail)
        self.refusal = refusal


DEFAULT_TOLERANCE_SECONDS = 300
"""Five minutes. Wide enough for provider retries and modest clock skew, narrow
enough that a captured body stops working; the replay guard covers the rest."""

MAX_REPLAY_KEYS = 10_000


@dataclass
class ReplayGuard:
    """Remember accepted delivery ids for the tolerance window, bounded.

    Insertion-ordered and pruned from the oldest end, because every key expires at
    the same age. ``now`` is injectable so the window is tested without sleeping.
    """

    window_seconds: float = DEFAULT_TOLERANCE_SECONDS
    max_keys: int = MAX_REPLAY_KEYS
    _seen: dict[str, float] = field(default_factory=dict)
    _now: Callable[[], float] = time.monotonic

    def claim(self, key: str) -> bool:
        """Record ``key``; return ``False`` when it is already inside the window."""
        now = self._now()
        self._prune(now)
        seen_at = self._seen.get(key)
        if seen_at is not None and now - seen_at < self.window_seconds:
            return False
        self._seen[key] = now
        return True

    def _prune(self, now: float) -> None:
        while self._seen:
            oldest = next(iter(self._seen))
            if now - self._seen[oldest] < self.window_seconds:
                break
            del self._seen[oldest]
        bound = max(self.max_keys, 1)
        while len(self._seen) >= bound:
            del self._seen[next(iter(self._seen))]

    @property
    def tracked(self) -> int:
        return len(self._seen)


class WebhookVerdict(StrictModel):
    """What was verified, for the audit entry — never the body or the secret."""

    scheme: WebhookScheme
    delivery_id: str = Field(min_length=1, max_length=200)
    timestamp: int | None = None


def _constant_time_equal(expected: bytes, provided: bytes) -> bool:
    return hmac.compare_digest(expected, provided)


def _svix_expected(secret: str, delivery_id: str, timestamp: str, body: bytes) -> bytes:
    key = secret.removeprefix("whsec_")
    try:
        key_bytes = base64.b64decode(key, validate=True)
    except ValueError as exc:
        raise WebhookError(
            WebhookRefusal.INVALID_SECRET, "the webhook secret is not a valid Svix key"
        ) from exc
    signed = f"{delivery_id}.{timestamp}.".encode() + body
    return base64.b64encode(hmac.new(key_bytes, signed, hashlib.sha256).digest())


def _meta_expected(secret: str, body: bytes) -> bytes:
    return hmac.new(secret.encode(), body, hashlib.sha256).hexdigest().encode()


def verify_webhook(
    *,
    scheme: WebhookScheme,
    headers: Mapping[str, str],
    body: bytes,
    secret: str,
    guard: ReplayGuard | None = None,
    tolerance_seconds: float = DEFAULT_TOLERANCE_SECONDS,
    now: float | None = None,
) -> WebhookVerdict:
    """Verify one delivery, or raise :class:`WebhookError` naming the refusal.

    Header lookup is case-insensitive because HTTP header names are, and the
    providers disagree on casing (``X-Hub-Signature-256`` vs ``x-hub-signature-256``).
    """
    lowered = {name.lower(): value for name, value in headers.items()}
    current = time.time() if now is None else now

    # Dispatch on the value rather than an ``is`` chain: a closed two-member enum
    # makes the final ``else`` statically unreachable, and a guard that mypy
    # reports as dead code is one somebody eventually deletes.
    if scheme.value == WebhookScheme.SVIX.value:
        delivery_id = lowered.get("svix-id", "")
        timestamp = lowered.get("svix-timestamp", "")
        signature_header = lowered.get("svix-signature", "")
        if not (delivery_id and timestamp and signature_header):
            raise WebhookError(
                WebhookRefusal.MISSING_HEADERS,
                "svix-id, svix-timestamp and svix-signature are required",
            )
        try:
            sent_at = int(timestamp)
        except ValueError as exc:
            raise WebhookError(
                WebhookRefusal.STALE_TIMESTAMP, "svix-timestamp is not a number"
            ) from exc
        if abs(current - sent_at) > tolerance_seconds:
            raise WebhookError(
                WebhookRefusal.STALE_TIMESTAMP,
                f"delivery is outside the {int(tolerance_seconds)}s tolerance",
            )
        expected = _svix_expected(secret, delivery_id, timestamp, body)
        provided = [
            version.removeprefix("v1,").encode()
            for version in signature_header.split()
            if version.startswith("v1,")
        ]
        if not provided or not any(
            _constant_time_equal(expected, candidate) for candidate in provided
        ):
            raise WebhookError(WebhookRefusal.BAD_SIGNATURE, "no matching v1 signature")
        verdict = WebhookVerdict(scheme=scheme, delivery_id=delivery_id, timestamp=sent_at)
    elif scheme.value == WebhookScheme.META.value:
        signature_header = lowered.get("x-hub-signature-256", "")
        delivery_id = lowered.get("x-hub-delivery-id") or lowered.get("x-request-id") or ""
        if not signature_header:
            raise WebhookError(WebhookRefusal.MISSING_HEADERS, "x-hub-signature-256 is required")
        if not delivery_id:
            raise WebhookError(
                WebhookRefusal.MISSING_HEADERS,
                "a delivery id header is required to guard against replays",
            )
        meta_signature = signature_header.removeprefix("sha256=").encode()
        if not _constant_time_equal(_meta_expected(secret, body), meta_signature):
            raise WebhookError(WebhookRefusal.BAD_SIGNATURE, "signature does not match the body")
        verdict = WebhookVerdict(scheme=scheme, delivery_id=delivery_id)
    else:
        raise WebhookError(WebhookRefusal.UNKNOWN_SCHEME, f"unsupported scheme {scheme!r}")

    if guard is not None and not guard.claim(f"{scheme.value}:{verdict.delivery_id}"):
        raise WebhookError(WebhookRefusal.REPLAYED, "this delivery was already accepted")
    return verdict


def verified_headers(
    secret: str, delivery_id: str, body: bytes, *, timestamp: int
) -> dict[str, str]:
    """The headers a correct sender produces — for tests and operator probes.

    Deliberately public: an operator pointing a connector at a self-hosted
    deployment needs a way to prove the wiring without a live provider, and the
    test suite needs the same computation the verifier performs.
    """
    signature = _svix_expected(secret, delivery_id, str(timestamp), body).decode()
    return {
        "svix-id": delivery_id,
        "svix-timestamp": str(timestamp),
        "svix-signature": f"v1,{signature}",
    }
