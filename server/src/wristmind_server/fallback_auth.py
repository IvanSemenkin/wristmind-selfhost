from __future__ import annotations

import base64
import hashlib
import hmac
import json
import time
from dataclasses import dataclass


class FallbackTicketError(ValueError):
    pass


@dataclass(frozen=True)
class FallbackIdentity:
    device_id: str
    user_id: str
    expires_at: int


def _encode(value: bytes) -> str:
    return base64.urlsafe_b64encode(value).rstrip(b"=").decode("ascii")


def _decode(value: str) -> bytes:
    padding = "=" * (-len(value) % 4)
    return base64.urlsafe_b64decode(value + padding)


def issue_fallback_ticket(device_id: str, user_id: str, expires_at: int, secret: str) -> str:
    payload = json.dumps(
        {"device_id": device_id, "user_id": user_id, "exp": expires_at},
        separators=(",", ":"),
        sort_keys=True,
    ).encode()
    encoded = _encode(payload)
    signature = hmac.new(secret.encode(), encoded.encode(), hashlib.sha256).digest()
    return f"{encoded}.{_encode(signature)}"


def verify_fallback_ticket(ticket: str, secret: str, *, now: int | None = None) -> FallbackIdentity:
    try:
        encoded, supplied_signature = ticket.split(".", 1)
        expected = hmac.new(secret.encode(), encoded.encode(), hashlib.sha256).digest()
        if not hmac.compare_digest(expected, _decode(supplied_signature)):
            raise FallbackTicketError("Invalid fallback ticket")
        payload = json.loads(_decode(encoded))
        identity = FallbackIdentity(
            device_id=str(payload["device_id"]),
            user_id=str(payload["user_id"]),
            expires_at=int(payload["exp"]),
        )
    except (KeyError, TypeError, ValueError, json.JSONDecodeError) as exc:
        if isinstance(exc, FallbackTicketError):
            raise
        raise FallbackTicketError("Invalid fallback ticket") from exc
    if identity.expires_at <= (int(time.time()) if now is None else now):
        raise FallbackTicketError("Fallback ticket expired")
    return identity
