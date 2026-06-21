from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.api.routes.auth import router as auth_router
from app.api.routes.scan import router as scan_router
from app.api.routes.user import router as user_router
from app.config import get_settings
from app.database import Base, engine
from app.migrate import apply_migrations

settings = get_settings()


@asynccontextmanager
async def lifespan(_app: FastAPI):
    Base.metadata.create_all(bind=engine)
    apply_migrations(engine)
    Path(settings.image_store_dir).mkdir(parents=True, exist_ok=True)
    yield


app = FastAPI(title="CheckImg", version="0.1.0", lifespan=lifespan)
_cors_allow_all = "*" in settings.cors_origins
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"] if _cors_allow_all else settings.cors_origins,
    allow_credentials=not _cors_allow_all,
    allow_methods=["*"],
    allow_headers=["*"],
)
app.include_router(scan_router)
app.include_router(auth_router)
app.include_router(user_router)


@app.get("/health")
def health():
    return {"status": "ok"}
