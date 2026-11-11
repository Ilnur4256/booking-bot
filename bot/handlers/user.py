import logging
import re
from datetime import datetime, timedelta, timezone

from aiogram import Bot, F, Router
from aiogram.filters import CommandStart
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.types import CallbackQuery, Message
from sqlalchemy.ext.asyncio import async_sessionmaker

from bot import keyboards as kb
from bot import services
from bot.config import Settings
from bot.db import Service
from bot.services import BookingError, WorkHours

router = Router(name="user")
log = logging.getLogger(__name__)

PHONE_RE = re.compile(r"^\+?\d[\d\s\-()]{7,18}$")


class BookingForm(StatesGroup):
    waiting_phone = State()


def work_hours(settings: Settings) -> WorkHours:
    return WorkHours(
        tz=settings.tz,
        start_hour=settings.work_start.hour,
        start_minute=settings.work_start.minute,
        end_hour=settings.work_end.hour,
        end_minute=settings.work_end.minute,
        step_minutes=settings.slot_step_minutes,
    )


def fmt_booking(b, settings: Settings) -> str:
    local = services.as_utc(b.starts_at).astimezone(settings.tz)
    return f"№{b.id} · {b.service.title} · {local:%d.%m %H:%M}"


@router.message(CommandStart())
async def start(message: Message, state: FSMContext) -> None:
    await state.clear()
    await message.answer(
        "Здравствуйте! Я бот записи в барбершоп.\n"
        "Выберите услугу, день и время — и я пришлю напоминание перед визитом.",
        reply_markup=kb.main_menu(),
    )


@router.message(F.text == kb.BTN_BOOK)
async def choose_service(
    message: Message, state: FSMContext, sessionmaker: async_sessionmaker
) -> None:
    await state.clear()
    async with sessionmaker() as session:
        items = await services.list_services(session)
    await message.answer("Выберите услугу:", reply_markup=kb.services_kb(items))


@router.callback_query(kb.ServiceCb.filter())
async def choose_day(call: CallbackQuery, callback_data: kb.ServiceCb, settings: Settings) -> None:
    today = datetime.now(settings.tz).date()
    days = [today + timedelta(days=i) for i in range(settings.booking_days_ahead)]
    await call.message.edit_text(
        "Выберите день:", reply_markup=kb.days_kb(callback_data.service_id, days)
    )
    await call.answer()


@router.callback_query(kb.DayCb.filter())
async def choose_slot(
    call: CallbackQuery,
    callback_data: kb.DayCb,
    settings: Settings,
    sessionmaker: async_sessionmaker,
) -> None:
    day = datetime.fromisoformat(callback_data.day).date()
    async with sessionmaker() as session:
        service = await session.get(Service, callback_data.service_id)
        slots = await services.available_slots(
            session, service, day, work_hours(settings), datetime.now(timezone.utc)
        )
    if not slots:
        await call.answer("На этот день свободного времени нет", show_alert=True)
        return
    await call.message.edit_text(
        f"{service.title}, {day:%d.%m}. Выберите время:",
        reply_markup=kb.slots_kb(service.id, slots),
    )
    await call.answer()


@router.callback_query(kb.SlotCb.filter())
async def ask_phone(
    call: CallbackQuery, callback_data: kb.SlotCb, state: FSMContext, settings: Settings
) -> None:
    await state.set_state(BookingForm.waiting_phone)
    await state.update_data(service_id=callback_data.service_id, ts=callback_data.ts)
    local = datetime.fromtimestamp(callback_data.ts, settings.tz)
    await call.message.edit_text(f"Время: {local:%d.%m %H:%M}")
    await call.message.answer(
        "Отправьте номер телефона кнопкой ниже или напишите его сообщением.",
        reply_markup=kb.phone_request(),
    )
    await call.answer()


@router.message(BookingForm.waiting_phone)
async def finish_booking(
    message: Message,
    state: FSMContext,
    bot: Bot,
    settings: Settings,
    sessionmaker: async_sessionmaker,
) -> None:
    phone = message.contact.phone_number if message.contact else (message.text or "").strip()
    if not PHONE_RE.match(phone):
        await message.answer("Не похоже на номер телефона. Пример: +996 555 123 456")
        return

    data = await state.get_data()
    starts_at = datetime.fromtimestamp(data["ts"], timezone.utc)
    async with sessionmaker() as session:
        service = await session.get(Service, data["service_id"])
        try:
            booking = await services.create_booking(
                session,
                user_id=message.from_user.id,
                user_name=message.from_user.full_name,
                phone=phone,
                service=service,
                starts_at=starts_at,
                now=datetime.now(timezone.utc),
            )
        except BookingError as e:
            await state.clear()
            await message.answer(str(e), reply_markup=kb.main_menu())
            return

    await state.clear()
    text = fmt_booking(booking, settings)
    await message.answer(f"✅ Вы записаны: {text}", reply_markup=kb.main_menu())

    for admin_id in settings.admin_ids:
        try:
            await bot.send_message(
                admin_id, f"🆕 Новая запись {text}\n{booking.user_name}, {booking.phone}"
            )
        except Exception:  # админ мог не запускать бота — запись от этого не должна падать
            log.exception("Не удалось уведомить администратора %s", admin_id)


@router.message(F.text == kb.BTN_MY)
async def my_bookings(
    message: Message, settings: Settings, sessionmaker: async_sessionmaker
) -> None:
    async with sessionmaker() as session:
        items = await services.user_upcoming_bookings(
            session, message.from_user.id, datetime.now(timezone.utc)
        )
    if not items:
        await message.answer("У вас нет предстоящих записей.")
        return
    lines = "\n".join(fmt_booking(b, settings) for b in items)
    await message.answer(f"Ваши записи:\n{lines}", reply_markup=kb.my_bookings_kb(items))


@router.callback_query(kb.CancelCb.filter())
async def cancel(
    call: CallbackQuery,
    callback_data: kb.CancelCb,
    bot: Bot,
    settings: Settings,
    sessionmaker: async_sessionmaker,
) -> None:
    async with sessionmaker() as session:
        try:
            booking = await services.cancel_booking(
                session, callback_data.booking_id, call.from_user.id
            )
        except BookingError as e:
            await call.answer(str(e), show_alert=True)
            return
    await call.message.edit_text(f"Запись №{booking.id} отменена.")
    await call.answer()
    for admin_id in settings.admin_ids:
        try:
            await bot.send_message(
                admin_id, f"❌ Клиент отменил запись {fmt_booking(booking, settings)}"
            )
        except Exception:
            log.exception("Не удалось уведомить администратора %s", admin_id)
