"""Integration tests for app.py — lifespan wiring and the DAV middleware."""

from unittest.mock import patch

import pytest
import pytest_asyncio
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient
from sqlalchemy.ext.asyncio import create_async_engine
from sqlalchemy.pool import StaticPool

from gdm_carddav.app import app, lifespan
from gdm_carddav.models import Base
from gdm_carddav.settings import Settings, get_settings

_TEST_SETTINGS = Settings(
    DATABASE_URL="sqlite+aiosqlite:///:memory:",
    CARDDAV_USERNAME="testuser",
    CARDDAV_PASSWORD="testpass",
    CARDDAV_REALM="test",
)
_AUTH = ("testuser", "testpass")


# ---------------------------------------------------------------------------
# Lifespan
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_lifespan_sets_session_factory() -> None:
    fake_app = FastAPI()
    with patch("gdm_carddav.app.get_settings", return_value=_TEST_SETTINGS):
        async with lifespan(fake_app):
            assert hasattr(fake_app.state, "session_factory")
            assert callable(fake_app.state.session_factory)


@pytest.mark.asyncio
async def test_lifespan_session_factory_yields_sessions() -> None:
    fake_app = FastAPI()
    with patch("gdm_carddav.app.get_settings", return_value=_TEST_SETTINGS):
        async with lifespan(fake_app):
            async with fake_app.state.session_factory() as session:
                assert session is not None


# ---------------------------------------------------------------------------
# Middleware + router smoke tests via the real app instance
# ---------------------------------------------------------------------------


@pytest_asyncio.fixture
async def full_client():
    engine = create_async_engine(
        "sqlite+aiosqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

    with (
        patch("gdm_carddav.app.get_settings", return_value=_TEST_SETTINGS),
        patch("gdm_carddav.app.make_engine", return_value=engine),
    ):
        app.dependency_overrides[get_settings] = lambda: _TEST_SETTINGS
        async with AsyncClient(
            transport=ASGITransport(app=app),
            base_url="http://test",
            auth=_AUTH,
            follow_redirects=False,
        ) as c:
            yield c
        app.dependency_overrides.pop(get_settings, None)

    await engine.dispose()


@pytest.mark.asyncio
async def test_dav_middleware_on_options(full_client: AsyncClient) -> None:
    response = await full_client.request("OPTIONS", "/")
    assert response.headers.get("DAV") == "1, 3, addressbook"


@pytest.mark.asyncio
async def test_dav_middleware_on_propfind(full_client: AsyncClient) -> None:
    response = await full_client.request("PROPFIND", "/")
    assert response.status_code == 207
    assert response.headers.get("DAV") == "1, 3, addressbook"


@pytest.mark.asyncio
async def test_app_router_registered_well_known(full_client: AsyncClient) -> None:
    response = await full_client.get("/.well-known/carddav")
    assert response.status_code == 301
    assert "contacts" in response.headers["location"]
