from datetime import datetime
from typing import Optional

from sqlalchemy import func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from .models import People


class PeopleRepository:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    def _base_filter(self):
        """Visibility filter: non-deceased, approved, with a non-empty email."""
        return (
            or_(People.estDecede == False, People.estDecede.is_(None)),  # noqa: E712
            # People.status.like("approved"),
            People.email.isnot(None),
            People.email != "",
        )

    async def get_all(self) -> list[People]:
        result = await self._session.execute(select(People).where(*self._base_filter()))
        return list(result.scalars().all())

    async def get_by_id(self, person_id: int) -> Optional[People]:
        result = await self._session.execute(
            select(People).where(People.id == person_id, *self._base_filter())
        )
        return result.scalar_one_or_none()

    async def get_by_ids(self, ids: list[int]) -> list[People]:
        result = await self._session.execute(
            select(People).where(People.id.in_(ids), *self._base_filter())
        )
        return list(result.scalars().all())

    async def get_max_updated_at(self) -> Optional[datetime]:
        result = await self._session.execute(
            select(func.max(People.updatedAt)).where(*self._base_filter())
        )
        return result.scalar_one_or_none()

    async def get_changed_since(self, since: datetime) -> list[People]:
        result = await self._session.execute(
            select(People).where(People.updatedAt > since, *self._base_filter())
        )
        return list(result.scalars().all())
