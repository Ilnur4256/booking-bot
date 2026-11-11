"""Бизнес-логика записи. Не зависит от Telegram — поэтому её легко тестировать."""

from dataclasses import dataclass
from datetime import date, datetime, timedelta, timezone
from zoneinfo import ZoneInfo

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from bot.db import Booking, BookingStatus, Service

DEFAULT_SERVICES = [
    ("Мужская стрижка", 45, 600),
    ("Стрижка + борода", 60, 900),
    ("Детская стрижка", 30, 400),
]


class BookingError(Exception):
    """Ошибка, текст которой можно показать пользователю."""


class SlotTakenError(BookingError):
    pass


@dataclass(frozen=True)
class WorkHours:
    tz: ZoneInfo
    start_hour: int
    start_minute: int
    end_hour: int
    end_minute: int
    step_minutes: int


def as_utc(dt: datetime) -> datetime:
    """SQLite возвращает время без часового пояса — считаем его UTC."""
    if dt.tzinfo is None:
        return dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


async def seed_services(session: AsyncSession) -> None:
    exists = await session.scalar(select(Service.id).limit(1))
    if exists:
        return
    for title, duration, price in DEFAULT_SERVICES:
        session.add(Service(title=title, duration_minutes=duration, price=price))
    await session.commit()


async def list_services(session: AsyncSession) -> list[Service]:
    result = await session.scalars(
        select(Service).where(Service.is_active.is_(True)).order_by(Service.id)
    )
    return list(result)


async def _active_bookings_between(
    session: AsyncSession, start: datetime, end: datetime
) -> list[Booking]:
    result = await session.scalars(
        select(Booking).where(
            Booking.status == BookingStatus.ACTIVE,
            Booking.starts_at < end,
            Booking.ends_at > start,
        )
    )
    return list(result)


def _overlaps(start: datetime, end: datetime, booking: Booking) -> bool:
    return start < as_utc(booking.ends_at) and as_utc(booking.starts_at) < end


async def available_slots(
    session: AsyncSession,
    service: Service,
    day: date,
    hours: WorkHours,
    now: datetime,
) -> list[datetime]:
    """Свободные времена начала для услуги в выбранный день (в местном времени)."""
    day_start = datetime(
        day.year, day.month, day.day, hours.start_hour, hours.start_minute, tzinfo=hours.tz
    )
    day_end = datetime(
        day.year, day.month, day.day, hours.end_hour, hours.end_minute, tzinfo=hours.tz
    )
    duration = timedelta(minutes=service.duration_minutes)
    step = timedelta(minutes=hours.step_minutes)

    busy = await _active_bookings_between(
        session, day_start.astimezone(timezone.utc), day_end.astimezone(timezone.utc)
    )

    slots: list[datetime] = []
    current = day_start
    while current + duration <= day_end:
        start_utc = current.astimezone(timezone.utc)
        end_utc = start_utc + duration
        is_future = start_utc > now
        is_free = not any(_overlaps(start_utc, end_utc, b) for b in busy)
        if is_future and is_free:
            slots.append(current)
        current += step
    return slots


async def create_booking(
    session: AsyncSession,
    *,
    user_id: int,
    user_name: str,
    phone: str,
    service: Service,
    starts_at: datetime,
    now: datetime,
) -> Booking:
    start_utc = as_utc(starts_at)
    end_utc = start_utc + timedelta(minutes=service.duration_minutes)
    if start_utc <= now:
        raise BookingError("Это время уже прошло, выберите другое.")

    # Повторная проверка прямо перед сохранением: пока клиент вводил телефон,
    # слот мог занять кто-то другой.
    busy = await _active_bookings_between(session, start_utc, end_utc)
    if busy:
        raise SlotTakenError("Это время только что заняли. Выберите другое, пожалуйста.")

    booking = Booking(
        user_id=user_id,
        user_name=user_name,
        phone=phone,
        service_id=service.id,
        starts_at=start_utc,
        ends_at=end_utc,
        created_at=now,
    )
    session.add(booking)
    await session.commit()
    await session.refresh(booking, ["service"])
    return booking


async def user_upcoming_bookings(
    session: AsyncSession, user_id: int, now: datetime
) -> list[Booking]:
    result = await session.scalars(
        select(Booking)
        .where(
            Booking.user_id == user_id,
            Booking.status == BookingStatus.ACTIVE,
            Booking.starts_at > now,
        )
        .order_by(Booking.starts_at)
    )
    return list(result)


async def cancel_booking(session: AsyncSession, booking_id: int, user_id: int | None) -> Booking:
    """Отменяет запись. user_id=None — отмена администратором (любая запись)."""
    booking = await session.get(Booking, booking_id)
    if booking is None or booking.status != BookingStatus.ACTIVE:
        raise BookingError("Запись не найдена или уже отменена.")
    if user_id is not None and booking.user_id != user_id:
        raise BookingError("Можно отменить только свою запись.")
    booking.status = BookingStatus.CANCELLED
    await session.commit()
    return booking


async def bookings_for_day(session: AsyncSession, day: date, tz: ZoneInfo) -> list[Booking]:
    start = datetime(day.year, day.month, day.day, tzinfo=tz).astimezone(timezone.utc)
    end = start + timedelta(days=1)
    result = await session.scalars(
        select(Booking)
        .where(
            Booking.status == BookingStatus.ACTIVE,
            Booking.starts_at >= start,
            Booking.starts_at < end,
        )
        .order_by(Booking.starts_at)
    )
    return list(result)


async def due_reminders(session: AsyncSession, now: datetime, hours_before: int) -> list[Booking]:
    """Записи, до которых осталось меньше hours_before часов и о которых ещё не напомнили."""
    result = await session.scalars(
        select(Booking).where(
            Booking.status == BookingStatus.ACTIVE,
            Booking.reminded.is_(False),
            Booking.starts_at > now,
            Booking.starts_at <= now + timedelta(hours=hours_before),
        )
    )
    return list(result)
