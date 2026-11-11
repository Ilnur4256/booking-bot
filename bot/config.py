from datetime import time
from typing import Annotated
from zoneinfo import ZoneInfo

from pydantic import field_validator
from pydantic_settings import BaseSettings, NoDecode, SettingsConfigDict


class Settings(BaseSettings):
    """Настройки читаются из переменных окружения или файла .env."""

    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8")

    bot_token: str
    database_url: str = "sqlite+aiosqlite:///booking.db"
    admin_ids: Annotated[list[int], NoDecode] = []
    timezone: str = "Asia/Bishkek"
    work_start: time = time(9, 0)
    work_end: time = time(19, 0)
    slot_step_minutes: int = 30
    booking_days_ahead: int = 7
    reminder_hours_before: int = 2

    @field_validator("admin_ids", mode="before")
    @classmethod
    def parse_admin_ids(cls, value: object) -> object:
        # Разрешаем писать в .env просто: ADMIN_IDS=123,456
        if isinstance(value, str):
            return [int(x) for x in value.split(",") if x.strip()]
        if isinstance(value, int):
            return [value]
        return value

    @property
    def tz(self) -> ZoneInfo:
        return ZoneInfo(self.timezone)
