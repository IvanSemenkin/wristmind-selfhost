from __future__ import annotations

import hashlib
import hmac
import ipaddress
import secrets
from datetime import datetime, timezone

from fastapi import Depends, Header, HTTPException, Request, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from .config import Settings, get_settings
from .database import get_session
from .db_models import Device


def hash_secret(value: str, settings: Settings) -> str:
    pepper = settings.token_pepper.get_secret_value()
    return hashlib.sha256(f"{pepper}:{value}".encode()).hexdigest()


def issue_pairing_code(
    client_request_id: str,
    device_id: str,
    derivation_counter: int,
    settings: Settings,
) -> str:
    """Derive a retry-safe six-digit code without storing the raw code."""
    pepper = settings.token_pepper.get_secret_value().encode()
    payload = f"pairing:{device_id}:{client_request_id}:{derivation_counter}".encode()
    digest = hmac.new(pepper, payload, hashlib.sha256).digest()
    return f"{int.from_bytes(digest[:8], 'big') % 1_000_000:06d}"


def issue_device_token(device_id: str) -> str:
    return f"wm_{device_id}.{secrets.token_urlsafe(32)}"


def client_ip(request: Request) -> str | None:
    """Use the client address appended by the public VPS, not a supplied prefix.

    The VPS and backend nginx each append one X-Forwarded-For entry. A caller
    may prepend arbitrary entries, so only the penultimate one is trusted.
    """
    forwarded = [part.strip() for part in request.headers.get("x-forwarded-for", "").split(",")]
    candidate = forwarded[-2] if len(forwarded) >= 2 else request.client.host if request.client else ""
    try:
        address = ipaddress.ip_address(candidate)
    except ValueError:
        return None
    return str(address) if address.is_global else None


async def current_device(
    request: Request,
    authorization: str | None = Header(None),
    session: AsyncSession = Depends(get_session),
    settings: Settings = Depends(get_settings),
) -> Device:
    if not authorization or not authorization.startswith("Bearer "):
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Device token required")
    raw = authorization.removeprefix("Bearer ").strip()
    device = await session.scalar(select(Device).where(Device.token_hash == hash_secret(raw, settings)))
    if not device or device.revoked_at is not None:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid device token")
    device.last_seen_at = datetime.now(timezone.utc)
    address = client_ip(request)
    if address:
        device.last_ip = address
    agent = request.headers.get("user-agent", "").strip()
    if agent:
        device.user_agent = agent[:300]
    await session.commit()
    return device


async def admin_device(device: Device = Depends(current_device)) -> Device:
    if not device.is_admin:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Admin device required")
    return device
