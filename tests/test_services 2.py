from datetime import date, datetime, timedelta, timezone
from zoneinfo import ZoneInfo

import pytest

from bot import services
from bot.services import BookingError, SlotTakenError, WorkHours

TZ = ZoneInfo("Asia/Bishkek")  # UTC+6
HOURS = WorkHours(tz=TZ, start_hour=9, start_minute=0, end_hour=12, end_minute=0, step_minutes=30)
DAY = date(2030, 1, 15)
NOW = datetime(2030, 1, 14, 12, 0, tzinfo=timezone.utc)


def local(h: int, m: int = 0) -> datetime:
    return datetime(DAY.year, DAY.month, DAY.day, h, m, tzinfo=TZ)


async def first_service(session):
    return (await services.list_services(session))[0]  # 45 минут


async def book(session, service, start, user_id=1):
    return await services.create_booking(
        session,
        user_id=user_id,
        user_name="Тест",
        phone="+996555000000",
        service=service,
        starts_at=start,
        now=NOW,
    )


async def test_slots_for_empty_day(session):
    service = await first_service(session)
    slots = await services.available_slots(session, service, DAY, HOURS, NOW)
    # 9:00..11:00 с шагом 30 минут, услуга 45 минут должна закончиться до 12:00
    assert [s.strftime("%H:%M") for s in slots] == ["09:00", "09:30", "10:00", "10:30", "11:00"]


async def test_booked_time_is_excluded(session):
    service = await first_service(session)
    await book(session, service, local(10, 0))  # 10:00–10:45
    slots = await services.available_slots(session, service, DAY, HOURS, NOW)
    assert [s.strftime("%H:%M") for s in slots] == ["09:00", "11:00"]


async def test_past_slots_are_hidden(session):
    service = await first_service(session)
    now = local(10, 15).astimezone(timezone.utc)
    slots = await services.available_slots(session, service, DAY, HOURS, now)
    assert [s.strftime("%H:%M") for s in slots] == ["10:30", "11:00"]


async def test_double_booking_is_rejected(session):
    service = await first_service(session)
    await book(session, service, local(9, 0))
    with pytest.raises(SlotTakenError):
        await book(session, service, local(9, 30), user_id=2)


async def test_booking_in_past_is_rejected(session):
    service = await first_service(session)
    with pytest.raises(BookingError):
        await book(session, service, NOW - timedelta(hours=1))


async def test_cancel_frees_slot_and_checks_owner(session):
    service = await first_service(session)
    b = await book(session, service, local(9, 0), user_id=1)
    with pytest.raises(BookingError):
        await services.cancel_booking(session, b.id, user_id=2)
    await services.cancel_booking(session, b.id, user_id=1)
    slots = await services.available_slots(session, service, DAY, HOURS, NOW)
    assert slots[0].strftime("%H:%M") == "09:00"
    with pytest.raises(BookingError):
        await services.cancel_booking(session, b.id, user_id=1)


async def test_user_bookings_and_day_list(session):
    service = await first_service(session)
    await book(session, service, local(11, 0), user_id=7)
    await book(session, service, local(9, 0), user_id=7)
    await book(session, service, local(10, 0), user_id=8)
    mine = await services.user_upcoming_bookings(session, 7, NOW)
    assert [services.as_utc(b.starts_at).astimezone(TZ).hour for b in mine] == [9, 11]
    day = await services.bookings_for_day(session, DAY, TZ)
    assert len(day) == 3


async def test_due_reminders(session):
    service = await first_service(session)
    b = await book(session, service, local(11, 0))
    start = services.as_utc(b.starts_at)
    assert await services.due_reminders(session, start - timedelta(hours=3), 2) == []
    due = await services.due_reminders(session, start - timedelta(hours=1), 2)
    assert [x.id for x in due] == [b.id]
