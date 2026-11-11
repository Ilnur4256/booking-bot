import asyncio
import logging
from datetime import datetime, timezone

from aiogram import Bot, Dispatcher
from sqlalchemy.ext.asyncio import async_sessionmaker

from bot import services
from bot.config import Settings
from bot.db import create_tables, make_engine, make_sessionmaker
from bot.handlers import admin, user

log = logging.getLogger(__name__)


async def reminder_loop(bot: Bot, sessionmaker: async_sessionmaker, settings: Settings) -> None:
    """Раз в минуту ищет записи, о которых пора напомнить."""
    while True:
        try:
            async with sessionmaker() as session:
                due = await services.due_reminders(
                    session, datetime.now(timezone.utc), settings.reminder_hours_before
                )
                for b in due:
                    local = services.as_utc(b.starts_at).astimezone(settings.tz)
                    try:
                        await bot.send_message(
                            b.user_id,
                            f"⏰ Напоминание: {b.service.title} {local:%d.%m в %H:%M}. Ждём вас!",
                        )
                    except Exception:
                        log.exception("Не удалось отправить напоминание по записи %s", b.id)
                    b.reminded = True
                await session.commit()
        except Exception:
            log.exception("Ошибка в цикле напоминаний")
        await asyncio.sleep(60)


async def main() -> None:
    logging.basicConfig(
        level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s"
    )
    settings = Settings()
    engine = make_engine(settings.database_url)
    await create_tables(engine)
    sessionmaker = make_sessionmaker(engine)
    async with sessionmaker() as session:
        await services.seed_services(session)

    bot = Bot(settings.bot_token)
    dp = Dispatcher()
    # Эти объекты aiogram передаёт в обработчики по имени аргумента
    dp["settings"] = settings
    dp["sessionmaker"] = sessionmaker
    dp.include_routers(admin.router, user.router)

    reminders = asyncio.create_task(reminder_loop(bot, sessionmaker, settings))
    try:
        await dp.start_polling(bot)
    finally:
        reminders.cancel()
        await engine.dispose()


if __name__ == "__main__":
    asyncio.run(main())
