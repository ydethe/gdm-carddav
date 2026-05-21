# Project: gdm_carddav

## Stack
- Python 3.12 + FastAPI 0.110
- SQLAlchemy 2.x (async)
- Pydantic v2
- PostgreSQL 16

## Commands
- Run: `uvicorn app.main:app --reload`
- Test: `pytest -v`
- Lint: `ruff check .`

## Architecture
- Layers: Router → Service → Repository
- No DB calls in Routers
- No HTTP types in Services
- DI via FastAPI's Depends()

## Code Rules
- Type annotations required (mypy strict)
- No `Any` type without justification comment
- No `print()` in production code (use loguru)
- All async functions must handle errors

## Security
- All SQL via SQLAlchemy ORM (no raw strings)
- All external input validated with Pydantic
- Secrets only via pydantic-settings, never hardcoded
- No passwords/tokens in logs

## Testing
- pytest + pytest-asyncio
- `@pytest.mark.asyncio` decorator required
- DB: SQLite in-memory for tests
- Pattern: AAA (Arrange, Act, Assert)
