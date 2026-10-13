import asyncio
import os
from pathlib import Path

import pytest
from fastapi.testclient import TestClient


TEST_ROOT = Path(__file__).parent / ".runtime"
TEST_ROOT.mkdir(parents=True, exist_ok=True)
os.environ["WRISTMIND_DATABASE_URL"] = (
    "sqlite+aiosqlite:///" + (TEST_ROOT / "wristmind-test.db").as_posix()
)
os.environ["WRISTMIND_STORAGE_DIR"] = str(TEST_ROOT / "private")
os.environ["WRISTMIND_BOOTSTRAP_SECRET"] = "test-bootstrap"
os.environ["WRISTMIND_TOKEN_PEPPER"] = "test-pepper"
os.environ["WRISTMIND_FALLBACK_TICKET_SECRET"] = "test-fallback-signing-secret"
os.environ["WRISTMIND_DEEPSEEK_API_KEY"] = "test-deepseek-key"
os.environ["WRISTMIND_MOCK_PROVIDERS"] = "true"

from wristmind_server.database import Base, engine  # noqa: E402
from wristmind_server.main import app  # noqa: E402


async def _reset_database() -> None:
    async with engine.begin() as connection:
        await connection.run_sync(Base.metadata.drop_all)
        await connection.run_sync(Base.metadata.create_all)


@pytest.fixture(autouse=True)
def deterministic_resources(monkeypatch):
    # Host/container pressure is tested explicitly with injected snapshots.
    # Functional tests must not depend on the CI machine's current load.
    from wristmind_server import resource_controller
    monkeypatch.setattr(resource_controller, 'linux_sample', lambda: resource_controller.ResourceSample())


@pytest.fixture(autouse=True)
def clean_database():
    asyncio.run(_reset_database())
    yield
    asyncio.run(_reset_database())


@pytest.fixture
def client():
    with TestClient(app) as test_client:
        yield test_client


@pytest.fixture
def admin(client: TestClient) -> dict[str, str]:
    response = client.post(
        "/v1/devices/admin/enroll",
        headers={"X-WristMind-Bootstrap": "test-bootstrap"},
        json={"name": "Test phone", "kind": "PHONE"},
    )
    assert response.status_code == 200, response.text
    return response.json()


@pytest.fixture
def admin_headers(admin: dict[str, str]) -> dict[str, str]:
    return {"Authorization": f"Bearer {admin['token']}"}


@pytest.fixture
def mode(client: TestClient, admin_headers: dict[str, str]) -> dict:
    response = client.post(
        "/v1/modes",
        headers=admin_headers,
        json={
            "name": "Математика",
            "color": "#65F5C2",
            "icon": "calculate",
            "system_prompt": "Решай задачи по шагам.",
            "response_model_id": "openrouter:google/gemini-2.5-flash-lite",
        },
    )
    assert response.status_code == 201, response.text
    return response.json()
