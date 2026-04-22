from __future__ import annotations

from contextlib import asynccontextmanager
from pathlib import Path
from typing import AsyncIterator
from urllib.parse import urlparse

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from app.config import get_settings
from app.db.models import Base

_settings = get_settings()


def _ensure_sqlite_dir(url: str) -> None:
    """For SQLite URLs, ensure the parent directory of the file exists."""
    if not url.startswith("sqlite"):
        return
    parsed = urlparse(url)
    # sqlite+aiosqlite:///./data/advert_bot.sqlite -> path is "/./data/advert_bot.sqlite"
    # sqlite+aiosqlite:///:memory: -> path is "/:memory:"
    raw_path = parsed.path.lstrip("/")
    if not raw_path or raw_path.startswith(":memory:"):
        return
    db_path = Path(raw_path)
    db_path.parent.mkdir(parents=True, exist_ok=True)


_ensure_sqlite_dir(_settings.database_url)

engine = create_async_engine(
    _settings.database_url,
    echo=False,
    pool_pre_ping=True,
    future=True,
)

AsyncSessionLocal = async_sessionmaker(
    engine,
    class_=AsyncSession,
    expire_on_commit=False,
)


async def init_db() -> None:
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)


@asynccontextmanager
async def session_scope() -> AsyncIterator[AsyncSession]:
    session = AsyncSessionLocal()
    try:
        yield session
        await session.commit()
    except Exception:
        await session.rollback()
        raise
    finally:
        await session.close()
