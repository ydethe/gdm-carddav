import asyncio

from gdm_carddav.repository import PeopleRepository
from gdm_carddav.database import get_db, make_engine, make_session_factory
from gdm_carddav.settings import get_settings


async def test_get_all_returns_eligible_contacts() -> None:
    settings = get_settings()
    engine = make_engine(settings.DATABASE_URL)

    session_manager = make_session_factory(engine)

    async for session in get_db(session_manager):
        repo = PeopleRepository(session)
        results = await repo.get_all()
        print(len(results))
        print(results[0].email)


if __name__ == "__main__":
    asyncio.run(test_get_all_returns_eligible_contacts())
