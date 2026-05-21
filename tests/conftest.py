from datetime import datetime

import pytest
import pytest_asyncio
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from gdm_carddav.models import Base, People


@pytest_asyncio.fixture
async def db_engine():
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    yield engine
    await engine.dispose()


@pytest_asyncio.fixture
async def session(db_engine) -> AsyncSession:
    factory = async_sessionmaker(db_engine, expire_on_commit=False)
    async with factory() as s:
        yield s


def make_person(**kwargs) -> People:
    defaults = dict(
        prenom="Jean",
        nom="Dupont",
        sexe="Homme",
        email="jean@example.com",
        status="approved",
        estDecede=False,
        updatedAt=datetime(2025, 1, 15, 10, 0, 0),
        createdAt=datetime(2025, 1, 1, 0, 0, 0),
    )
    defaults.update(kwargs)
    return People(**defaults)
