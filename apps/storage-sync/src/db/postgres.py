from sqlalchemy.ext.asyncio import create_async_engine, async_sessionmaker, AsyncSession
from config.settings import settings

engine = create_async_engine(settings.database_url.replace("postgresql://", "postgresql+asyncpg://"), echo=False)
AsyncSessionLocal = async_sessionmaker(
    bind=engine,
    class_=AsyncSession,
    expire_on_commit=False
)
