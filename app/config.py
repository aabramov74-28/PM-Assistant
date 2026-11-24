"""Конфигурация приложения: чтение .env без внешних зависимостей."""

from __future__ import annotations

import os
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent


def _load_dotenv(path: Path) -> None:
    """Минимальный парсер .env (KEY=VALUE, # — комментарий)."""
    if not path.exists():
        return
    for raw in path.read_text(encoding="utf-8").splitlines():
        line = raw.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, value = line.partition("=")
        key, value = key.strip(), value.strip().strip('"').strip("'")
        if key and key not in os.environ:
            os.environ[key] = value


_load_dotenv(PROJECT_ROOT / ".env")


def _get(key: str, default: str = "") -> str:
    return os.environ.get(key, default).strip()


class Settings:
    """Единая точка доступа к настройкам."""

    # Telegram
    TELEGRAM_BOT_TOKEN: str = _get("TELEGRAM_BOT_TOKEN")
    ADMIN_TG_IDS: frozenset[int] = frozenset(
        int(x) for x in _get("ADMIN_TG_IDS").split(",") if x.strip().isdigit()
    )

    # Расписания
    DIGEST_TIME: str = _get("DIGEST_TIME", "09:00")
    WEEKLY_REPORT_DAY: int = int(_get("WEEKLY_REPORT_DAY", "4"))  # 0=Пн … 4=Пт
    WEEKLY_REPORT_TIME: str = _get("WEEKLY_REPORT_TIME", "17:00")
    EOD_SURVEY_TIME: str = _get("EOD_SURVEY_TIME", "18:00")
    TZ: str = _get("TZ", "Europe/Moscow")

    # Почта (неделя 4)
    SMTP_HOST: str = _get("SMTP_HOST")
    SMTP_PORT: int = int(_get("SMTP_PORT", "465"))
    SMTP_USER: str = _get("SMTP_USER")
    SMTP_PASSWORD: str = _get("SMTP_PASSWORD")
    IMAP_HOST: str = _get("IMAP_HOST")
    IMAP_PORT: int = int(_get("IMAP_PORT", "993"))
    IMAP_USER: str = _get("IMAP_USER")
    IMAP_PASSWORD: str = _get("IMAP_PASSWORD")
    MAIL_FROM_ADDRESS: str = _get("MAIL_FROM_ADDRESS")  # по умолчанию SMTP_USER

    # Яндекс 360 Календарь (неделя 4)
    CALDAV_URL: str = _get("CALDAV_URL", "https://caldav.yandex.ru")
    CALDAV_USER: str = _get("CALDAV_USER")
    CALDAV_PASSWORD: str = _get("CALDAV_PASSWORD")

    # LLM (неделя 3)
    LLM_BASE_URL: str = _get("LLM_BASE_URL")
    LLM_API_KEY: str = _get("LLM_API_KEY")
    LLM_MODEL: str = _get("LLM_MODEL")
    LLM_FOLDER_ID: str = _get("LLM_FOLDER_ID")      # Yandex Cloud folder
    LLM_AUTH_SCHEME: str = _get("LLM_AUTH_SCHEME")  # Api-Key | Bearer (авто)

    DATABASE_PATH: str = _get("DATABASE_PATH", str(PROJECT_ROOT / "pm_assistant.db"))

    # --- Флаги доступности модулей ---
    @classmethod
    def telegram_enabled(cls) -> bool:
        return bool(cls.TELEGRAM_BOT_TOKEN)

    @classmethod
    def mail_enabled(cls) -> bool:
        return bool(cls.SMTP_HOST and cls.SMTP_USER and cls.SMTP_PASSWORD)

    @classmethod
    def calendar_enabled(cls) -> bool:
        return bool(cls.CALDAV_USER and cls.CALDAV_PASSWORD)

    @classmethod
    def llm_enabled(cls) -> bool:
        return bool(cls.LLM_BASE_URL and cls.LLM_API_KEY and cls.LLM_MODEL)


def parse_hhmm(value: str) -> tuple[int, int]:
    """'09:00' -> (9, 0)."""
    hh, mm = value.split(":")
    return int(hh), int(mm)
