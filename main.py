"""Точка входа MVP «Ассистент PM»."""

from __future__ import annotations

import logging
import sys

from app.config import Settings
from app.db import connect
from app.repository import Repository


def main() -> None:
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    )
    log = logging.getLogger("pm_assistant")

    if not Settings.telegram_enabled():
        log.error("Не задан TELEGRAM_BOT_TOKEN. Скопируйте .env.example в .env "
                  "и заполните токен от @BotFather.")
        sys.exit(1)

    repo = Repository(connect(Settings.DATABASE_PATH))
    repo.audit("service_started", None, f"v0.1.0, tz={Settings.TZ}")

    # python-telegram-bot импортируем здесь: без токена сервис не стартует,
    # а тесты модулей не требуют установленного telegram-пакета.
    from telegram.ext import Application
    from app.bot import register_handlers
    from app.scheduler import setup_jobs

    app = Application.builder().token(Settings.TELEGRAM_BOT_TOKEN).build()
    app.bot_data["repo"] = repo
    register_handlers(app)
    setup_jobs(app)

    log.info("Ассистент PM запущен. Модули: почта=%s, календарь=%s, LLM=%s",
             "on" if Settings.mail_enabled() else "off",
             "on" if Settings.calendar_enabled() else "off",
             "on" if Settings.llm_enabled() else "off")
    app.run_polling()


if __name__ == "__main__":
    main()
