"""HTTP integration tests for the CardDAV router.

Uses a test FastAPI app with:
- In-memory SQLite via StaticPool (shared single connection)
- get_db overridden to use the test session
- get_settings overridden with test credentials
"""

from contextlib import asynccontextmanager
from xml.etree import ElementTree as ET

import pytest
import pytest_asyncio
from fastapi import FastAPI, Request
from httpx import ASGITransport, AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.pool import StaticPool

from gdm_carddav.models import Base
from gdm_carddav.router import get_db, router
from gdm_carddav.settings import Settings, get_settings
from tests.conftest import make_person

_D = "DAV:"
_C = "urn:ietf:params:xml:ns:carddav"
_CS = "http://calendarserver.org/ns/"

_TEST_USER = "testuser"
_TEST_PASS = "testpass"
_AUTH = (_TEST_USER, _TEST_PASS)

_TEST_SETTINGS = Settings(
    DATABASE_URL="sqlite+aiosqlite:///:memory:",
    CARDDAV_USERNAME=_TEST_USER,
    CARDDAV_PASSWORD=_TEST_PASS,
    CARDDAV_REALM="test",
)


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest_asyncio.fixture
async def router_engine():
    engine = create_async_engine(
        "sqlite+aiosqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    yield engine
    await engine.dispose()


@pytest_asyncio.fixture
async def router_session(router_engine) -> AsyncSession:
    factory = async_sessionmaker(router_engine, expire_on_commit=False)
    async with factory() as s:
        yield s


@pytest_asyncio.fixture
async def client(router_session: AsyncSession):
    def _make_get_db_override(session: AsyncSession):
        async def _override():
            yield session

        return _override

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        app.state.session_factory = None
        yield

    test_app = FastAPI(lifespan=lifespan)

    @test_app.middleware("http")
    async def add_dav_headers(request: Request, call_next):
        response = await call_next(request)
        response.headers["DAV"] = "1, 3, addressbook"
        return response

    test_app.include_router(router)
    test_app.dependency_overrides[get_settings] = lambda: _TEST_SETTINGS
    test_app.dependency_overrides[get_db] = _make_get_db_override(router_session)

    async with AsyncClient(
        transport=ASGITransport(app=test_app),
        base_url="http://test",
        auth=_AUTH,
        follow_redirects=False,
    ) as c:
        yield c


# ---------------------------------------------------------------------------
# Auth tests
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_unauthorized_returns_401(client: AsyncClient) -> None:
    c = AsyncClient(
        transport=client._transport,  # reuse same transport
        base_url="http://test",
        follow_redirects=False,
    )
    async with c:
        response = await c.request("PROPFIND", "/")
    assert response.status_code == 401
    assert "WWW-Authenticate" in response.headers


@pytest.mark.asyncio
async def test_wrong_password_returns_401(client: AsyncClient) -> None:
    c = AsyncClient(
        transport=client._transport,
        base_url="http://test",
        auth=(_TEST_USER, "wrongpass"),
        follow_redirects=False,
    )
    async with c:
        response = await c.request("PROPFIND", "/")
    assert response.status_code == 401


# ---------------------------------------------------------------------------
# Discovery
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_well_known_redirect(client: AsyncClient) -> None:
    response = await client.get("/.well-known/carddav")
    assert response.status_code == 301
    assert f"/principals/{_TEST_USER}/contacts/" in response.headers["location"]


@pytest.mark.asyncio
async def test_options_returns_allow_header(client: AsyncClient) -> None:
    response = await client.request("OPTIONS", "/")
    assert response.status_code == 200
    assert "PROPFIND" in response.headers["allow"]


@pytest.mark.asyncio
async def test_propfind_root_returns_207(client: AsyncClient) -> None:
    response = await client.request("PROPFIND", "/")
    assert response.status_code == 207
    root = ET.fromstring(response.content)
    href_texts = [el.text for el in root.findall(f".//{{{_D}}}href")]
    assert "/" in href_texts


@pytest.mark.asyncio
async def test_propfind_root_contains_current_user_principal(client: AsyncClient) -> None:
    response = await client.request("PROPFIND", "/")
    root = ET.fromstring(response.content)
    cup = root.find(f".//{{{_D}}}current-user-principal")
    assert cup is not None
    href = cup.find(f"{{{_D}}}href")
    assert href is not None
    assert _TEST_USER in href.text


@pytest.mark.asyncio
async def test_propfind_principal_returns_207(client: AsyncClient) -> None:
    response = await client.request("PROPFIND", f"/principals/{_TEST_USER}/")
    assert response.status_code == 207


@pytest.mark.asyncio
async def test_propfind_principal_contains_addressbook_home_set(client: AsyncClient) -> None:
    response = await client.request("PROPFIND", f"/principals/{_TEST_USER}/")
    root = ET.fromstring(response.content)
    home = root.find(f".//{{{_C}}}addressbook-home-set")
    assert home is not None


# ---------------------------------------------------------------------------
# Collection PROPFIND
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_propfind_collection_empty(client: AsyncClient) -> None:
    response = await client.request(
        "PROPFIND",
        f"/principals/{_TEST_USER}/contacts/",
        headers={"Depth": "0"},
    )
    assert response.status_code == 207
    root = ET.fromstring(response.content)
    # Should have resourcetype with collection + addressbook
    rt = root.find(f".//{{{_D}}}resourcetype")
    assert rt is not None
    assert rt.find(f"{{{_C}}}addressbook") is not None


@pytest.mark.asyncio
async def test_propfind_collection_has_sync_token(client: AsyncClient) -> None:
    response = await client.request(
        "PROPFIND", f"/principals/{_TEST_USER}/contacts/", headers={"Depth": "0"}
    )
    root = ET.fromstring(response.content)
    token_el = root.find(f".//{{{_D}}}sync-token")
    assert token_el is not None
    assert token_el.text is not None


@pytest.mark.asyncio
async def test_propfind_collection_depth1_lists_contacts(
    client: AsyncClient, router_session: AsyncSession
) -> None:
    # Arrange
    router_session.add(make_person(id=1, nom="Dupont"))
    await router_session.commit()

    # Act
    response = await client.request(
        "PROPFIND", f"/principals/{_TEST_USER}/contacts/", headers={"Depth": "1"}
    )

    # Assert
    assert response.status_code == 207
    root = ET.fromstring(response.content)
    hrefs = [el.text for el in root.findall(f".//{{{_D}}}href")]
    assert any("gdm-1@gdm_carddav.vcf" in h for h in hrefs)


# ---------------------------------------------------------------------------
# Contact PROPFIND / GET / HEAD
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_propfind_contact_returns_207(
    client: AsyncClient, router_session: AsyncSession
) -> None:
    router_session.add(make_person(id=7))
    await router_session.commit()

    response = await client.request(
        "PROPFIND", f"/principals/{_TEST_USER}/contacts/gdm-7@gdm_carddav.vcf"
    )
    assert response.status_code == 207
    root = ET.fromstring(response.content)
    etag_el = root.find(f".//{{{_D}}}getetag")
    assert etag_el is not None
    assert "7-" in etag_el.text


@pytest.mark.asyncio
async def test_propfind_contact_not_found(client: AsyncClient) -> None:
    response = await client.request(
        "PROPFIND", f"/principals/{_TEST_USER}/contacts/gdm-9999@gdm_carddav.vcf"
    )
    assert response.status_code == 404


@pytest.mark.asyncio
async def test_get_contact_returns_vcard(client: AsyncClient, router_session: AsyncSession) -> None:
    router_session.add(make_person(id=1, prenom="Jean", nom="Dupont"))
    await router_session.commit()

    response = await client.get(f"/principals/{_TEST_USER}/contacts/gdm-1@gdm_carddav.vcf")

    assert response.status_code == 200
    assert "text/vcard" in response.headers["content-type"]
    assert "BEGIN:VCARD" in response.text
    assert "FN:Jean Dupont" in response.text


@pytest.mark.asyncio
async def test_get_contact_has_etag(client: AsyncClient, router_session: AsyncSession) -> None:
    router_session.add(make_person(id=2))
    await router_session.commit()

    response = await client.get(f"/principals/{_TEST_USER}/contacts/gdm-2@gdm_carddav.vcf")
    assert "ETag" in response.headers
    assert response.headers["ETag"].startswith('"2-')


@pytest.mark.asyncio
async def test_get_contact_not_found(client: AsyncClient) -> None:
    response = await client.get(f"/principals/{_TEST_USER}/contacts/gdm-9999@gdm_carddav.vcf")
    assert response.status_code == 404


@pytest.mark.asyncio
async def test_head_contact_returns_etag(client: AsyncClient, router_session: AsyncSession) -> None:
    router_session.add(make_person(id=3))
    await router_session.commit()

    response = await client.head(f"/principals/{_TEST_USER}/contacts/gdm-3@gdm_carddav.vcf")
    assert response.status_code == 200
    assert "ETag" in response.headers


# ---------------------------------------------------------------------------
# REPORT — addressbook-multiget
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_report_multiget(client: AsyncClient, router_session: AsyncSession) -> None:
    router_session.add(make_person(id=1, prenom="Jean", nom="Dupont"))
    router_session.add(make_person(id=2, prenom="Marie", nom="Martin"))
    await router_session.commit()

    body = (
        f'<C:addressbook-multiget xmlns:D="DAV:" xmlns:C="{_C}">'
        f"<D:prop><D:getetag/><C:address-data/></D:prop>"
        f"<D:href>/principals/{_TEST_USER}/contacts/gdm-1@gdm_carddav.vcf</D:href>"
        f"</C:addressbook-multiget>"
    )
    response = await client.request(
        "REPORT",
        f"/principals/{_TEST_USER}/contacts/",
        content=body.encode(),
        headers={"Content-Type": "application/xml"},
    )

    assert response.status_code == 207
    root = ET.fromstring(response.content)
    hrefs = [el.text for el in root.findall(f".//{{{_D}}}href")]
    assert any("gdm-1@gdm_carddav.vcf" in h for h in hrefs)
    # Only id=1 was requested
    assert not any("gdm-2@gdm_carddav.vcf" in (h or "") for h in hrefs)
    # vCard data is embedded
    addr_data = root.find(f".//{{{_C}}}address-data")
    assert addr_data is not None
    assert "BEGIN:VCARD" in addr_data.text


# ---------------------------------------------------------------------------
# REPORT — addressbook-query
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_report_addressbook_query_returns_all(
    client: AsyncClient, router_session: AsyncSession
) -> None:
    router_session.add(make_person(id=1))
    router_session.add(make_person(id=2))
    await router_session.commit()

    body = (
        f'<C:addressbook-query xmlns:D="DAV:" xmlns:C="{_C}">'
        "<D:prop><D:getetag/><C:address-data/></D:prop>"
        "</C:addressbook-query>"
    )
    response = await client.request(
        "REPORT",
        f"/principals/{_TEST_USER}/contacts/",
        content=body.encode(),
        headers={"Content-Type": "application/xml"},
    )

    assert response.status_code == 207
    root = ET.fromstring(response.content)
    hrefs = [el.text for el in root.findall(f".//{{{_D}}}href")]
    contact_hrefs = [h for h in hrefs if h and ".vcf" in h]
    assert len(contact_hrefs) == 2


# ---------------------------------------------------------------------------
# REPORT — sync-collection
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_report_sync_collection_initial(
    client: AsyncClient, router_session: AsyncSession
) -> None:
    router_session.add(make_person(id=1))
    await router_session.commit()

    body = (
        f'<D:sync-collection xmlns:D="DAV:" xmlns:C="{_C}">'
        "<D:sync-token/>"
        "<D:sync-level>1</D:sync-level>"
        "<D:prop><D:getetag/></D:prop>"
        "</D:sync-collection>"
    )
    response = await client.request(
        "REPORT",
        f"/principals/{_TEST_USER}/contacts/",
        content=body.encode(),
        headers={"Content-Type": "application/xml"},
    )

    assert response.status_code == 207
    root = ET.fromstring(response.content)
    # New sync-token is embedded in multistatus
    token_el = root.find(f"{{{_D}}}sync-token")
    assert token_el is not None
    assert token_el.text.startswith("https://gdm_carddav/sync/")


@pytest.mark.asyncio
async def test_report_sync_collection_incremental(
    client: AsyncClient, router_session: AsyncSession
) -> None:
    from datetime import datetime, timezone

    router_session.add(make_person(id=1, nom="Old", updatedAt=datetime(2025, 1, 1)))
    router_session.add(make_person(id=2, nom="New", updatedAt=datetime(2025, 6, 1)))
    await router_session.commit()

    since = datetime(2025, 3, 1, tzinfo=timezone.utc)
    ts_us = int(since.timestamp() * 1_000_000)
    token = f"https://gdm_carddav/sync/{ts_us}"

    body = (
        f'<D:sync-collection xmlns:D="DAV:" xmlns:C="{_C}">'
        f"<D:sync-token>{token}</D:sync-token>"
        "<D:sync-level>1</D:sync-level>"
        "<D:prop><D:getetag/></D:prop>"
        "</D:sync-collection>"
    )
    response = await client.request(
        "REPORT",
        f"/principals/{_TEST_USER}/contacts/",
        content=body.encode(),
        headers={"Content-Type": "application/xml"},
    )

    assert response.status_code == 207
    root = ET.fromstring(response.content)
    hrefs = [el.text for el in root.findall(f".//{{{_D}}}href")]
    contact_hrefs = [h for h in hrefs if h and ".vcf" in h]
    # Only the new contact (id=2) should appear
    assert len(contact_hrefs) == 1
    assert "gdm-2@gdm_carddav.vcf" in contact_hrefs[0]


# ---------------------------------------------------------------------------
# Write no-ops
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_put_returns_201(client: AsyncClient) -> None:
    response = await client.put(
        f"/principals/{_TEST_USER}/contacts/gdm-99@gdm_carddav.vcf",
        content=b"BEGIN:VCARD\r\nVERSION:3.0\r\nEND:VCARD\r\n",
    )
    assert response.status_code == 201


@pytest.mark.asyncio
async def test_delete_returns_204(client: AsyncClient) -> None:
    response = await client.delete(f"/principals/{_TEST_USER}/contacts/gdm-99@gdm_carddav.vcf")
    assert response.status_code == 204


@pytest.mark.asyncio
async def test_mkcol_returns_201(client: AsyncClient) -> None:
    response = await client.request("MKCOL", f"/principals/{_TEST_USER}/newcol/")
    assert response.status_code == 201


@pytest.mark.asyncio
async def test_proppatch_returns_207(client: AsyncClient) -> None:
    body = '<D:propertyupdate xmlns:D="DAV:"><D:set><D:prop><D:displayname>X</D:displayname></D:prop></D:set></D:propertyupdate>'
    response = await client.request(
        "PROPPATCH",
        f"/principals/{_TEST_USER}/contacts/",
        content=body.encode(),
    )
    assert response.status_code == 207


# ---------------------------------------------------------------------------
# DAV header
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_dav_header_on_get(client: AsyncClient, router_session: AsyncSession) -> None:
    router_session.add(make_person(id=1))
    await router_session.commit()

    response = await client.get(f"/principals/{_TEST_USER}/contacts/gdm-1@gdm_carddav.vcf")
    assert response.headers.get("DAV") == "1, 3, addressbook"


@pytest.mark.asyncio
async def test_dav_header_on_propfind(client: AsyncClient) -> None:
    response = await client.request("PROPFIND", "/")
    assert response.headers.get("DAV") == "1, 3, addressbook"
