from datetime import datetime, timezone

from loguru import logger

from gdm_carddav.models import People
from gdm_carddav.repository import PeopleRepository
from gdm_carddav.vcard import compute_etag, people_to_vcard

_ContactTuple = tuple[People, str, str]  # (person, etag, vcard_str)


class CardDAVService:
    SYNC_PREFIX = "https://gdm_carddav/sync/"

    def __init__(self, repo: PeopleRepository) -> None:
        self._repo = repo

    def _make_tuple(self, person: People) -> _ContactTuple:
        return (person, compute_etag(person), people_to_vcard(person))

    async def get_all(self) -> list[_ContactTuple]:
        people = await self._repo.get_all()
        return [self._make_tuple(p) for p in people]

    async def get_by_id(self, person_id: int) -> _ContactTuple | None:
        person = await self._repo.get_by_id(person_id)
        if person is None:
            return None
        return self._make_tuple(person)

    async def get_by_ids(self, ids: list[int]) -> list[_ContactTuple]:
        people = await self._repo.get_by_ids(ids)
        return [self._make_tuple(p) for p in people]

    async def get_ctag(self) -> str | None:
        max_updated = await self._repo.get_max_updated_at()
        if max_updated is None:
            return None
        return str(int(max_updated.timestamp()))

    async def get_sync_token(self) -> str:
        max_updated = await self._repo.get_max_updated_at()
        if max_updated is None:
            ts_us = 0
        else:
            ts_us = int(max_updated.timestamp() * 1_000_000)
        return f"{self.SYNC_PREFIX}{ts_us}"

    def _token_to_datetime(self, token: str) -> datetime | None:
        if not token.startswith(self.SYNC_PREFIX):
            return None
        raw = token[len(self.SYNC_PREFIX) :]
        try:
            ts_us = int(raw)
        except ValueError:
            return None
        return datetime.fromtimestamp(ts_us / 1_000_000, tz=timezone.utc)

    async def get_changes_since(self, token: str) -> list[_ContactTuple]:
        since = self._token_to_datetime(token)
        if since is None:
            logger.warning("Invalid sync token {!r}, falling back to full sync", token)
            return await self.get_all()
        people = await self._repo.get_changed_since(since)
        return [self._make_tuple(p) for p in people]
