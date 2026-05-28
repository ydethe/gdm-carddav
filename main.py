import asyncio

from loguru import logger

from gdm_carddav.repository import PeopleRepository
from gdm_carddav.database import get_db, make_engine, make_session_factory
from gdm_carddav.settings import get_settings


async def main() -> None:
    settings = get_settings()
    engine = make_engine(settings.DATABASE_URL)

    session_manager = make_session_factory(engine)

    async for session in get_db(session_manager):
        repo = PeopleRepository(session)
        results = await repo.get_all()
        logger.info("Found {} contacts", len(results))
        if results:
            logger.info("First contact email: {}", results[0].email)


if __name__ == "__main__":
    asyncio.run(main())
