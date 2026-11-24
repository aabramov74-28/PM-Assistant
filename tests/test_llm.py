"""Тесты LLM-модуля с подменой httpx (внешний API не вызывается).

Запуск: python tests/test_llm.py
"""

from __future__ import annotations

import json
import sys
import types
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.config import Settings
from app.integrations.llm import LLMModule

FAILED = 0
CAPTURED: dict = {}


def check(name: str, condition: bool, detail: str = "") -> None:
    global FAILED
    mark = "✅" if condition else "❌"
    if not condition:
        FAILED += 1
    print(f"{mark} {name}" + (f" — {detail}" if detail and not condition else ""))


def fake_httpx(payload_text: str | Exception):
    """Фейковый модуль httpx: post() возвращает заданный текст модели."""
    module = types.ModuleType("httpx")

    class FakeResponse:
        def raise_for_status(self):
            if isinstance(payload_text, Exception):
                raise payload_text

        def json(self):
            return {"choices": [{"message": {"content": payload_text}}]}

    def post(url, headers=None, json=None, timeout=None):
        CAPTURED["url"] = url
        CAPTURED["headers"] = headers
        CAPTURED["json"] = json
        return FakeResponse()

    module.post = post
    return module


def enable_llm(base_url: str = "https://llm.api.cloud.yandex.net/v1") -> None:
    Settings.LLM_BASE_URL = base_url
    Settings.LLM_API_KEY = "test-key"
    Settings.LLM_MODEL = "gpt://folder123/yandexgpt-lite/latest"
    Settings.LLM_FOLDER_ID = "folder123"
    Settings.LLM_AUTH_SCHEME = ""


def disable_llm() -> None:
    Settings.LLM_BASE_URL = ""
    Settings.LLM_API_KEY = ""
    Settings.LLM_MODEL = ""
    Settings.LLM_FOLDER_ID = ""


def with_fake(payload, fn):
    sys.modules["httpx"] = fake_httpx(payload)
    try:
        return fn()
    finally:
        sys.modules.pop("httpx", None)


def main() -> None:
    enable_llm()

    # 1. Счастливый путь: чистый JSON
    def case_happy():
        return LLMModule().parse_status_reply("в работе, процентов 70 готово")
    r = with_fake('{"status": "in_progress", "progress": 70, "comment": "готово 70%"}',
                  case_happy)
    check("Парсинг чистого JSON",
          r["status"] == "in_progress" and r["progress"] == 70
          and r["comment"] == "готово 70%", str(r))

    # 2. JSON в markdown-обёртке
    def case_fenced():
        return LLMModule().parse_status_reply("закончил, отдал на проверку")
    r = with_fake('Вот разбор:\n```json\n{"status": "on_review", "progress": null, "comment": "отдал на проверку"}\n```',
                  case_fenced)
    check("Парсинг JSON в ```json обёртке", r["status"] == "on_review", str(r))

    # 3. Мусорный ответ модели → деградация unclear + исходный текст
    def case_garbage():
        return LLMModule().parse_status_reply("всё горит")
    r = with_fake("Не могу ответить на этот вопрос", case_garbage)
    check("Мусорный ответ → unclear + исходный текст",
          r["status"] == "unclear" and r["comment"] == "всё горит", str(r))

    # 4. Невалидный статус от модели → unclear
    def case_bad_status():
        return LLMModule().parse_status_reply("что-то делаю")
    r = with_fake('{"status": "done_soon", "progress": 200, "comment": "x"}',
                  case_bad_status)
    check("Невалидный status/progress → unclear, progress=None",
          r["status"] == "unclear" and r["progress"] is None, str(r))

    # 5. Сетевая ошибка → деградация, без исключений
    def case_network():
        return LLMModule().parse_status_reply("свободный текст")
    r = with_fake(ConnectionError("no route to host"), case_network)
    check("Сетевая ошибка → unclear, исключений нет",
          r["status"] == "unclear" and r["comment"] == "свободный текст", str(r))

    # 6. Авторизация Yandex: Api-Key + OpenAI-Project
    with_fake('{"status": "done", "progress": 100, "comment": ""}',
              lambda: LLMModule().parse_status_reply("сделал"))
    check("Yandex: заголовок Api-Key",
          CAPTURED["headers"]["Authorization"] == "Api-Key test-key",
          str(CAPTURED["headers"].get("Authorization")))
    check("Yandex: заголовок OpenAI-Project = folder_id",
          CAPTURED["headers"].get("OpenAI-Project") == "folder123")

    # 7. Не-Yandex URL → Bearer
    enable_llm("https://api.openai.com/v1")
    with_fake('{"status": "done", "progress": null, "comment": ""}',
              lambda: LLMModule().parse_status_reply("сделал"))
    check("Не-Yandex: заголовок Bearer",
          CAPTURED["headers"]["Authorization"] == "Bearer test-key")
    enable_llm()

    # 8. summarize: счастливый путь и деградация
    def case_summary():
        return LLMModule().summarize("Проект А: выполнено 3, просрочено 1.")
    s = with_fake("Неделя прошла рабоче: закрыто 3 задачи, одна просрочена.",
                  case_summary)
    check("summarize возвращает текст модели", isinstance(s, str) and len(s) > 10)

    disable_llm()
    check("Без настроек: parse → unclear + комментарий",
          LLMModule().parse_status_reply("текст")["status"] == "unclear")
    check("Без настроек: summarize → None",
          LLMModule().summarize("факты") is None)
    ok, msg = LLMModule().healthcheck()
    check("Без настроек: healthcheck -> False", not ok)

    print()
    if FAILED:
        print(f"ПРОВАЛЕНО тестов: {FAILED}")
        sys.exit(1)
    print("Все LLM-проверки пройдены ✔")


if __name__ == "__main__":
    main()
