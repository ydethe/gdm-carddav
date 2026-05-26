from datetime import datetime, timezone

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from gdm_carddav.repository import PeopleRepository
from gdm_carddav.service import CardDAVService
from tests.conftest import make_person


def _svc(session: AsyncSession) -> CardDAVService:
    return CardDAVService(PeopleRepository(session))


# ---------------------------------------------------------------------------
# get_all
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_get_all_returns_triples(session: AsyncSession) -> None:
    # Arrange
    session.add(make_person(id=1))
    await session.commit()

    # Act
    results = await _svc(session).get_all()

    # Assert
    assert len(results) == 1
    person, etag, vcard = results[0]
    assert person.id == 1
    assert etag.startswith('"1-')
    assert "BEGIN:VCARD" in vcard


@pytest.mark.asyncio
async def test_get_all_empty(session: AsyncSession) -> None:
    assert await _svc(session).get_all() == []


# ---------------------------------------------------------------------------
# get_by_id
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_get_by_id_found(session: AsyncSession) -> None:
    # Arrange
    session.add(make_person(id=42))
    await session.commit()

    # Act
    result = await _svc(session).get_by_id(42)

    # Assert
    assert result is not None
    person, etag, vcard = result
    assert person.id == 42
    assert "gdm-42@gdm_carddav" in vcard


@pytest.mark.asyncio
async def test_get_by_id_not_found(session: AsyncSession) -> None:
    result = await _svc(session).get_by_id(999)
    assert result is None


# ---------------------------------------------------------------------------
# get_by_ids
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_get_by_ids_returns_subset(session: AsyncSession) -> None:
    # Arrange
    session.add(make_person(id=1, nom="Alpha"))
    session.add(make_person(id=2, nom="Beta"))
    session.add(make_person(id=3, nom="Gamma"))
    await session.commit()

    # Act
    results = await _svc(session).get_by_ids([1, 3])

    # Assert
    noms = {t[0].nom for t in results}
    assert noms == {"Alpha", "Gamma"}


# ---------------------------------------------------------------------------
# get_ctag
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_get_ctag_is_digit_string(session: AsyncSession) -> None:
    session.add(make_person(id=1, updatedAt=datetime(2025, 1, 15, 10, 0, 0, tzinfo=timezone.utc)))
    await session.commit()

    ctag = await _svc(session).get_ctag()

    assert ctag is not None
    assert ctag.isdigit()


@pytest.mark.asyncio
async def test_get_ctag_none_when_empty(session: AsyncSession) -> None:
    assert await _svc(session).get_ctag() is None


# ---------------------------------------------------------------------------
# get_sync_token
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_get_sync_token_format(session: AsyncSession) -> None:
    session.add(make_person(id=1))
    await session.commit()

    token = await _svc(session).get_sync_token()

    assert token.startswith("https://gdm_carddav/sync/")
    suffix = token.removeprefix("https://gdm_carddav/sync/")
    assert suffix.isdigit()


@pytest.mark.asyncio
async def test_get_sync_token_zero_when_empty(session: AsyncSession) -> None:
    assert await _svc(session).get_sync_token() == "https://gdm_carddav/sync/0"


# ---------------------------------------------------------------------------
# get_changes_since
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_get_changes_since_valid_token(session: AsyncSession) -> None:
    # Arrange: one old, one new
    session.add(make_person(id=1, nom="Old", updatedAt=datetime(2025, 1, 1)))
    session.add(make_person(id=2, nom="New", updatedAt=datetime(2025, 6, 1)))
    await session.commit()

    since = datetime(2025, 3, 1, tzinfo=timezone.utc)
    ts_us = int(since.timestamp() * 1_000_000)
    token = f"https://gdm_carddav/sync/{ts_us}"

    # Act
    results = await _svc(session).get_changes_since(token)

    # Assert
    noms = {t[0].nom for t in results}
    assert "New" in noms
    assert "Old" not in noms


@pytest.mark.asyncio
async def test_get_changes_since_invalid_token_returns_all(session: AsyncSession) -> None:
    # Arrange
    session.add(make_person(id=1))
    session.add(make_person(id=2))
    await session.commit()

    # Act — invalid token falls back to full sync
    results = await _svc(session).get_changes_since("not-a-valid-token")

    assert len(results) == 2


# ---------------------------------------------------------------------------
# _token_to_datetime
# ---------------------------------------------------------------------------


def test_token_to_datetime_valid() -> None:
    svc = CardDAVService(None)  # type: ignore[arg-type]
    dt = svc._token_to_datetime("https://gdm_carddav/sync/1000000")
    assert dt is not None
    assert dt.tzinfo is not None


def test_token_to_datetime_invalid_prefix() -> None:
    svc = CardDAVService(None)  # type: ignore[arg-type]
    assert svc._token_to_datetime("https://other/sync/1000000") is None


def test_token_to_datetime_non_numeric() -> None:
    svc = CardDAVService(None)  # type: ignore[arg-type]
    assert svc._token_to_datetime("https://gdm_carddav/sync/abc") is None
