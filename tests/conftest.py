import pytest_asyncio

from bot.db import create_tables, make_engine, make_sessionmaker
from bot.services import seed_services


@pytest_asyncio.fixture
async def session():
    engine = make_engine("sqlite+aiosqlite:///:memory:")
    await create_tables(engine)
    maker = make_sessionmaker(engine)
    async with maker() as s:
        await seed_services(s)
        yield s
    await engine.dispose()
