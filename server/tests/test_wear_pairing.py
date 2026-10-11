import asyncio

import pytest

from wristmind_server.database import SessionFactory
from wristmind_server.db_models import Device, User


def enroll(client, admin_headers, kind="WATCH"):
    code = client.post("/v1/devices/pairing-codes", headers=admin_headers).json()["code"]
    response = client.post(
        "/v1/devices/enroll", json={"name": "Test device", "kind": kind, "code": code},
    )
    assert response.status_code == 200
    device = response.json()
    return device, {"Authorization": f"Bearer {device['token']}"}


def test_owner_watch_issues_one_time_code_without_other_admin_access(client, admin_headers):
    watch, headers = enroll(client, admin_headers)
    assert watch["is_admin"] is False
    assert client.get("/v1/devices", headers=headers).status_code == 403
    created = client.post("/v1/devices/pairing-codes", headers=headers)
    assert created.status_code == 201
    assert len(created.json()["code"]) == 6
    assert created.json()["expires_at"]
    request = {"name": "New panel", "kind": "WEB", "code": created.json()["code"]}
    panel = client.post("/v1/devices/admin/enroll-by-code", json=request)
    assert panel.status_code == 200
    assert panel.json()["user_id"] == watch["user_id"]
    assert client.post("/v1/devices/admin/enroll-by-code", json=request).status_code == 401


@pytest.mark.parametrize("kind,role", [("PHONE", "ADMIN"), ("WATCH", "USER")])
def test_non_owner_watch_and_non_admin_phone_cannot_issue_codes(client, admin_headers, kind, role):
    device, headers = enroll(client, admin_headers, kind)

    async def set_owner_role():
        async with SessionFactory() as session:
            row = await session.get(Device, device["device_id"])
            owner = await session.get(User, row.user_id)
            owner.role = role
            await session.commit()

    asyncio.run(set_owner_role())
    assert client.post("/v1/devices/pairing-codes", headers=headers).status_code == 403


def test_revoked_owner_watch_cannot_issue_code(client, admin_headers):
    watch, headers = enroll(client, admin_headers)
    assert client.delete(f"/v1/devices/{watch['device_id']}", headers=admin_headers).status_code == 204
    assert client.post("/v1/devices/pairing-codes", headers=headers).status_code == 401
