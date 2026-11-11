from datetime import date, datetime

from aiogram.filters.callback_data import CallbackData
from aiogram.types import InlineKeyboardMarkup, KeyboardButton, ReplyKeyboardMarkup
from aiogram.utils.keyboard import InlineKeyboardBuilder

from bot.db import Booking, Service

WEEKDAYS = ["Пн", "Вт", "Ср", "Чт", "Пт", "Сб", "Вс"]

BTN_BOOK = "📅 Записаться"
BTN_MY = "🗂 Мои записи"


class ServiceCb(CallbackData, prefix="srv"):
    service_id: int


class DayCb(CallbackData, prefix="day"):
    service_id: int
    day: str  # ISO-дата: 2026-11-12


class SlotCb(CallbackData, prefix="slot"):
    service_id: int
    ts: int  # unix-время начала


class CancelCb(CallbackData, prefix="cancel"):
    booking_id: int


def main_menu() -> ReplyKeyboardMarkup:
    return ReplyKeyboardMarkup(
        keyboard=[[KeyboardButton(text=BTN_BOOK), KeyboardButton(text=BTN_MY)]],
        resize_keyboard=True,
    )


def phone_request() -> ReplyKeyboardMarkup:
    return ReplyKeyboardMarkup(
        keyboard=[[KeyboardButton(text="📱 Отправить номер", request_contact=True)]],
        resize_keyboard=True,
        one_time_keyboard=True,
    )


def services_kb(services: list[Service]) -> InlineKeyboardMarkup:
    kb = InlineKeyboardBuilder()
    for s in services:
        kb.button(
            text=f"{s.title} · {s.duration_minutes} мин · {s.price} сом",
            callback_data=ServiceCb(service_id=s.id),
        )
    kb.adjust(1)
    return kb.as_markup()


def days_kb(service_id: int, days: list[date]) -> InlineKeyboardMarkup:
    kb = InlineKeyboardBuilder()
    for d in days:
        kb.button(
            text=f"{WEEKDAYS[d.weekday()]} {d:%d.%m}",
            callback_data=DayCb(service_id=service_id, day=d.isoformat()),
        )
    kb.adjust(4)
    return kb.as_markup()


def slots_kb(service_id: int, slots: list[datetime]) -> InlineKeyboardMarkup:
    kb = InlineKeyboardBuilder()
    for s in slots:
        kb.button(
            text=f"{s:%H:%M}",
            callback_data=SlotCb(service_id=service_id, ts=int(s.timestamp())),
        )
    kb.adjust(4)
    return kb.as_markup()


def my_bookings_kb(bookings: list[Booking]) -> InlineKeyboardMarkup:
    kb = InlineKeyboardBuilder()
    for b in bookings:
        kb.button(text=f"❌ Отменить №{b.id}", callback_data=CancelCb(booking_id=b.id))
    kb.adjust(1)
    return kb.as_markup()
