from contextlib import asynccontextmanager

from fastapi import FastAPI, Request

from gdm_carddav.database import make_engine, make_session_factory
from gdm_carddav.router import router
from gdm_carddav.settings import get_settings


@asynccontextmanager
async def lifespan(app: FastAPI):
    settings = get_settings()
    engine = make_engine(settings.DATABASE_URL)
    app.state.session_factory = make_session_factory(engine)
    yield
    await engine.dispose()


app = FastAPI(title="gdm-carddav", lifespan=lifespan)


@app.middleware("http")
async def add_dav_headers(request: Request, call_next):
    response = await call_next(request)
    response.headers["DAV"] = "1, 3, addressbook"
    return response


app.include_router(router)
