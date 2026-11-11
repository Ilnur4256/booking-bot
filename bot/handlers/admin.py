from datetime import datetime, timedelta

from aiogram import Router
from aiogram.filters import Command, CommandObject, Filter
from aiogram.types import Message
from sqlalchemy.ext.asyncio import async_sessionmaker

from bot import services
from bot.config import Settings
from bot.services import BookingError

router = Router(name="admin")


class IsAdmin(Filter):
    async def __call__(self, message: Message, settings: Settings) -> bool:
        return message.from_user is not None and message.from_user.id in settings.admin_ids


router.message.filter(IsAdmin())


@router.message(Command("admin"))
async def help_(message: Message) -> None:
    await message.answer(
        "Команды администратора:\n"
        "/today — записи на сегодня\n"
        "/tomorrow — записи на завтра\n"
        "/cancel_booking <номер> — отменить запись клиента"
    )


async def _send_day(
    message: Message, settings: Settings, sessionmaker: async_sessionmaker, offset: int
) -> None:
    day = datetime.now(settings.tz).date() + timedelta(days=offset)
    async with sessionmaker() as session:
        items = await services.bookings_for_day(session, day, settings.tz)
    if not items:
        await message.answer(f"На {day:%d.%m} записей нет.")
        return
    lines = []
    for b in items:
        local = services.as_utc(b.starts_at).astimezone(settings.tz)
        lines.append(f"{local:%H:%M} · №{b.id} · {b.service.title} · {b.user_name}, {b.phone}")
    await message.answer(f"Записи на {day:%d.%m}:\n" + "\n".join(lines))


@router.message(Command("today"))
async def today(message: Message, settings: Settings, sessionmaker: async_sessionmaker) -> None:
    await _send_day(message, settings, sessionmaker, 0)


@router.message(Command("tomorrow"))
async def tomorrow(message: Message, settings: Settings, sessionmaker: async_sessionmaker) -> None:
    await _send_day(message, settings, sessionmaker, 1)


@router.message(Command("cancel_booking"))
async def cancel_booking(
    message: Message, command: CommandObject, sessionmaker: async_sessionmaker
) -> None:
    if not command.args or not command.args.strip().isdigit():
        await message.answer("Использование: /cancel_booking 12")
        return
    async with sessionmaker() as session:
        try:
            booking = await services.cancel_booking(session, int(command.args), user_id=None)
        except BookingError as e:
            await message.answer(str(e))
            return
    await message.answer(f"Запись №{booking.id} отменена.")
