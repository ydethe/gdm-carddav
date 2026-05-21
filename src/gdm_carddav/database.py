from collections.abc import AsyncGenerator
from typing import Any

from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)

# PostgreSQL user-defined enum types that asyncpg cannot decode without codecs.
# Registered as text on each new connection so the ORM can read them as strings.
_PG_ENUM_TYPES: list[tuple[str, str]] = [
    ("public", "enum_People_sexe"),
    ("public", "enum_People_status"),
    ("public", "enum_People_requestType"),
    ("public", "enum_People_familyStatus"),
]


async def _init_asyncpg(conn: Any) -> None:
    for schema, name in _PG_ENUM_TYPES:
        await conn.set_type_codec(
            name,
            encoder=str,
            decoder=str,
            schema=schema,
            format="text",
        )


def make_engine(database_url: str) -> AsyncEngine:
    kwargs: dict[str, Any] = {"pool_pre_ping": True}
    if "postgresql" in database_url:
        kwargs["connect_args"] = {"init": _init_asyncpg}
    return create_async_engine(database_url, **kwargs)


def make_session_factory(engine: AsyncEngine) -> async_sessionmaker[AsyncSession]:
    return async_sessionmaker(engine, expire_on_commit=False)


async def get_db(
    session_factory: async_sessionmaker[AsyncSession],
) -> AsyncGenerator[AsyncSession, None]:
    async with session_factory() as session:
        yield session
