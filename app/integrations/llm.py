"""LLM-модуль (раздел 5.7 ТЗ): разбор ответов исполнителей и резюме для отчётов.

Провайдер: YandexGPT через OpenAI-совместимый API
(https://llm.api.cloud.yandex.net/v1). Подойдёт и любой другой
OpenAI-совместимый сервис — схема авторизации выбирается автоматически
(Api-Key для Yandex, Bearer для остальных) или через LLM_AUTH_SCHEME.

Без настроек или при любой ошибке — деградированный режим (FR-29):
ответы сохраняются как комментарии, резюме не генерируются,
факты всегда берутся только из базы данных.
"""

from __future__ import annotations

import json
import re

from ..config import Settings

PARSE_PROMPT = (
    "Ты — парсер статусов задач проектного офиса. По ответу исполнителя верни "
    "СТРОГО JSON без пояснений и markdown-обёрток: "
    '{"status": "...", "progress": 0-100 или null, "comment": "..."}. '
    'status — одно из: in_progress, on_review, blocked, done, unclear. '
    "Если статус неясен — unclear. Никаких выдуманных фактов."
)

SUMMARY_PROMPT = (
    "Ты — ассистент проектного офиса. По фактам ниже напиши связное резюме "
    "на русском, 2–3 предложения, деловым тоном. Используй ТОЛЬКО приведённые "
    "факты и числа, ничего не придумывай и не додумывай."
)

FALLBACK = {"status": "unclear", "progress": None, "comment": ""}
VALID_STATUSES = ("in_progress", "on_review", "blocked", "done", "unclear")

_JSON_BLOCK = re.compile(r"\{.*\}", re.DOTALL)


class LLMModule:
    def __init__(self, repo=None):
        self.enabled = Settings.llm_enabled()
        self.repo = repo

    def _log(self, what: str, details: str) -> None:
        if self.repo:
            self.repo.audit(f"llm_{what}", None, details)

    # ---------------------------------------------------------------- низкий уровень

    def _chat(self, system: str, user: str, temperature: float = 0.0) -> str | None:
        """Один вызов chat/completions. None при любой ошибке (деградация)."""
        if not self.enabled:
            return None
        try:
            import httpx

            base = Settings.LLM_BASE_URL.rstrip("/")
            scheme = Settings.LLM_AUTH_SCHEME
            if not scheme:
                scheme = "Api-Key" if "yandex" in base else "Bearer"
            headers = {"Authorization": f"{scheme} {Settings.LLM_API_KEY}"}
            if Settings.LLM_FOLDER_ID:
                headers["OpenAI-Project"] = Settings.LLM_FOLDER_ID

            resp = httpx.post(
                f"{base}/chat/completions",
                headers=headers,
                json={
                    "model": Settings.LLM_MODEL,
                    "temperature": temperature,
                    "messages": [
                        {"role": "system", "content": system},
                        {"role": "user", "content": user},
                    ],
                },
                timeout=30,
            )
            resp.raise_for_status()
            return resp.json()["choices"][0]["message"]["content"].strip()
        except Exception as exc:
            self._log("fallback", str(exc)[:200])
            return None

    @staticmethod
    def _extract_json(text: str) -> dict | None:
        """Достаёт JSON-объект из ответа (модели любят оборачивать в ```json)."""
        match = _JSON_BLOCK.search(text)
        if not match:
            return None
        try:
            return json.loads(match.group(0))
        except (json.JSONDecodeError, ValueError):
            return None

    # ---------------------------------------------------------------- сценарии

    def parse_status_reply(self, text: str) -> dict:
        """Свободный текст -> {status, progress, comment}. Никогда не падает."""
        if not self.enabled:
            return {**FALLBACK, "comment": text}
        content = self._chat(PARSE_PROMPT, text)
        if content is None:
            return {**FALLBACK, "comment": text}
        parsed = self._extract_json(content)
        if not isinstance(parsed, dict):
            self._log("bad_json", content[:200])
            return {**FALLBACK, "comment": text}
        status = parsed.get("status", "unclear")
        if status not in VALID_STATUSES:
            status = "unclear"
        progress = parsed.get("progress")
        if not isinstance(progress, int) or not 0 <= progress <= 100:
            progress = None
        return {
            "status": status,
            "progress": progress,
            "comment": str(parsed.get("comment") or text),
        }

    def summarize(self, facts: str, context: str = "") -> str | None:
        """Связное резюме по фактам из БД (FR-27). None при деградации."""
        if not self.enabled:
            return None
        prompt = f"{context}\n\nФакты:\n{facts}" if context else f"Факты:\n{facts}"
        result = self._chat(SUMMARY_PROMPT, prompt, temperature=0.3)
        if result:
            self._log("summarized", context[:100] or "digest")
        return result

    def healthcheck(self) -> tuple[bool, str]:
        """Проверка живого подключения: для диагностики после заполнения .env."""
        if not self.enabled:
            return False, "Модуль не настроен: заполните LLM_* в .env"
        result = self._chat("Отвечай одним словом.", "работаешь?")
        if result is None:
            return False, "Вызов не прошёл — см. audit_log (llm_fallback)"
        return True, f"OK, ответ модели: {result[:80]}"
