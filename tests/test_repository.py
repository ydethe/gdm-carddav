from datetime import datetime

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from gdm_carddav.repository import PeopleRepository
from tests.conftest import make_person


@pytest.mark.asyncio
async def test_get_all_returns_eligible_contacts(session: AsyncSession) -> None:
    # Arrange
    session.add(make_person(id=1))
    await session.commit()

    # Act
    repo = PeopleRepository(session)
    results = await repo.get_all()

    # Assert
    assert len(results) == 1
    assert results[0].nom == "Dupont"


@pytest.mark.asyncio
async def test_get_all_excludes_deceased(session: AsyncSession) -> None:
    # Arrange
    session.add(make_person(id=1, estDecede=True))
    await session.commit()

    # Act
    results = await PeopleRepository(session).get_all()

    # Assert
    assert results == []


@pytest.mark.asyncio
async def test_get_all_excludes_null_deceased(session: AsyncSession) -> None:
    # A NULL estDecede is treated as alive and should be included.
    session.add(make_person(id=1, estDecede=None))
    await session.commit()

    results = await PeopleRepository(session).get_all()

    assert len(results) == 1


@pytest.mark.asyncio
async def test_get_all_excludes_null_email(session: AsyncSession) -> None:
    # Arrange
    session.add(make_person(id=1, email=None))
    await session.commit()

    # Act
    results = await PeopleRepository(session).get_all()

    # Assert
    assert results == []


@pytest.mark.asyncio
async def test_get_all_excludes_empty_email(session: AsyncSession) -> None:
    # Arrange
    session.add(make_person(id=1, email=""))
    await session.commit()

    # Act
    results = await PeopleRepository(session).get_all()

    # Assert
    assert results == []


@pytest.mark.asyncio
async def test_get_by_id_returns_match(session: AsyncSession) -> None:
    # Arrange
    session.add(make_person(id=42))
    await session.commit()

    # Act
    person = await PeopleRepository(session).get_by_id(42)

    # Assert
    assert person is not None
    assert person.id == 42


@pytest.mark.asyncio
async def test_get_by_id_returns_none_for_missing(session: AsyncSession) -> None:
    person = await PeopleRepository(session).get_by_id(999)
    assert person is None


@pytest.mark.asyncio
async def test_get_by_id_returns_none_for_ineligible(session: AsyncSession) -> None:
    # Arrange — deceased person should not be reachable by id
    session.add(make_person(id=7, estDecede=True))
    await session.commit()

    # Act
    person = await PeopleRepository(session).get_by_id(7)

    # Assert
    assert person is None


@pytest.mark.asyncio
async def test_get_by_ids_returns_matching_subset(session: AsyncSession) -> None:
    # Arrange
    session.add(make_person(id=1, nom="Alpha"))
    session.add(make_person(id=2, nom="Beta"))
    session.add(make_person(id=3, nom="Gamma"))
    await session.commit()

    # Act
    results = await PeopleRepository(session).get_by_ids([1, 3])

    # Assert
    noms = {p.nom for p in results}
    assert noms == {"Alpha", "Gamma"}


@pytest.mark.asyncio
async def test_get_by_ids_filters_ineligible(session: AsyncSession) -> None:
    # Arrange — id=2 is deceased, should be excluded even when explicitly requested
    session.add(make_person(id=1, nom="Alive"))
    session.add(make_person(id=2, nom="Dead", estDecede=True))
    await session.commit()

    # Act
    results = await PeopleRepository(session).get_by_ids([1, 2])

    # Assert
    assert len(results) == 1
    assert results[0].nom == "Alive"


@pytest.mark.asyncio
async def test_get_max_updated_at_returns_latest(session: AsyncSession) -> None:
    # Arrange
    session.add(make_person(id=1, updatedAt=datetime(2025, 1, 1)))
    session.add(make_person(id=2, updatedAt=datetime(2025, 6, 15)))
    session.add(make_person(id=3, updatedAt=datetime(2025, 3, 10)))
    await session.commit()

    # Act
    max_ts = await PeopleRepository(session).get_max_updated_at()

    # Assert
    assert max_ts == datetime(2025, 6, 15)


@pytest.mark.asyncio
async def test_get_max_updated_at_excludes_ineligible(session: AsyncSession) -> None:
    # Arrange — the newest record is deceased, so it must not contribute to the max
    session.add(make_person(id=1, updatedAt=datetime(2025, 1, 1)))
    session.add(make_person(id=2, estDecede=True, updatedAt=datetime(2026, 1, 1)))
    await session.commit()

    # Act
    max_ts = await PeopleRepository(session).get_max_updated_at()

    # Assert
    assert max_ts == datetime(2025, 1, 1)


@pytest.mark.asyncio
async def test_get_max_updated_at_none_when_empty(session: AsyncSession) -> None:
    max_ts = await PeopleRepository(session).get_max_updated_at()
    assert max_ts is None


@pytest.mark.asyncio
async def test_get_changed_since_returns_newer_contacts(session: AsyncSession) -> None:
    # Arrange
    session.add(make_person(id=1, nom="Old", updatedAt=datetime(2025, 1, 1)))
    session.add(make_person(id=2, nom="New", updatedAt=datetime(2025, 6, 1)))
    await session.commit()

    # Act
    results = await PeopleRepository(session).get_changed_since(datetime(2025, 3, 1))

    # Assert
    assert len(results) == 1
    assert results[0].nom == "New"


@pytest.mark.asyncio
async def test_get_changed_since_excludes_ineligible(session: AsyncSession) -> None:
    # Arrange — the newer record is deceased
    session.add(make_person(id=1, nom="Alive", updatedAt=datetime(2025, 6, 1)))
    session.add(make_person(id=2, nom="Dead", estDecede=True, updatedAt=datetime(2025, 6, 2)))
    await session.commit()

    # Act
    results = await PeopleRepository(session).get_changed_since(datetime(2025, 1, 1))

    # Assert
    assert len(results) == 1
    assert results[0].nom == "Alive"
