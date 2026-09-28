import json
import logging
import time
from datetime import datetime
from zoneinfo import ZoneInfo

from app.config import Settings
from app.llm import LLMClient
from app.storage import Storage
from app.tools import ToolRegistry

logger = logging.getLogger(__name__)


class AgentService:
    def __init__(
        self,
        settings: Settings,
        storage: Storage,
        llm_client: LLMClient,
        tools: ToolRegistry,
    ):
        self.settings = settings
        self.storage = storage
        self.llm_client = llm_client
        self.tools = tools

    # ============================ системные промпты ============================

    def _system_prompt_native(self) -> str:
        tz = ZoneInfo(self.settings.default_timezone)
        now = datetime.now(tz)

        return (
            "Ты — персональный AI-ассистент пользователя в Telegram.\n"
            "Отвечай кратко, ясно и по-русски, если пользователь пишет по-русски.\n"
            "Используй инструменты, когда нужны актуальные данные, память или действия.\n"
            "Не выдумывай заметки или задачи. Если нужен факт — вызови инструмент.\n"
            "Если пользователь просит что-то запомнить, используй add_note.\n"
            "Если пользователь спрашивает заметки, используй list_notes.\n\n"
            "ВРЕМЯ И ЧАСОВЫЕ ПОЯСА — КРИТИЧНО:\n"
            "Ты НЕ знаешь текущее время и НЕ знаешь разницу часовых поясов наизусть. "
            "Любой вопрос о том, который час, какое время или какая дата в любом городе, "
            "стране или часовом поясе, ОБЯЗАТЕЛЬНО требует вызова get_current_time. "
            "Никогда не вычисляй время самостоятельно и не отвечай наугад. "
            "Если пользователь назвал город, подбери IANA-зону и передай её в параметре "
            "timezone, например Asia/Tokyo, Europe/London, America/New_York, Europe/Moscow. "
            "Если город не назван и речь о локальном времени пользователя — передай "
            f"timezone={self.settings.default_timezone}.\n\n"
            f"Текущая дата и время: {now.strftime('%Y-%m-%d %H:%M')}\n"
            f"Часовой пояс пользователя по умолчанию: {self.settings.default_timezone}"
        )

    def _system_prompt_json(self) -> str:
        """
        Промпт для текстового протокола инструментов.

        ВНИМАНИЕ к скобкам: JSON-примеры и шаблон контракта намеренно собраны
        ОБЫЧНЫМИ строковыми литералами (без f-префикса). В f-строке фигурные
        скобки из {"tool": ...} пришлось бы удваивать ({{ }}) — это частый
        источник SyntaxError и тихо сломанного промпта. Подстановки даты/зоны/
        спецификации вынесены в отдельные f-части и склеиваются с литералами.
        """
        tz = ZoneInfo(self.settings.default_timezone)
        now = datetime.now(tz)

        header = (  # f-часть: здесь нет литеральных { }, только плейсхолдеры
            "Ты — персональный AI-ассистент пользователя в Telegram.\n"
            "Отвечай кратко, ясно и по-русски, если пользователь пишет по-русски.\n"
            "Используй инструменты, когда нужны актуальные данные, память или действия.\n"
            "Не выдумывай заметки, задачи или время. Если нужен факт — вызови инструмент.\n\n"
            f"Текущая дата и время: {now.strftime('%Y-%m-%d %H:%M')}\n"
            f"Часовой пояс: {self.settings.default_timezone}\n"
        )

        protocol = self.tools.get_json_protocol_spec()  # без { }, безопасно

        contract = (  # обычный литерал: { } остаются как есть, не экранируем
            "ПРОТОКОЛ ИНСТРУМЕНТОВ (текстовый режим).\n"
            "Если тебе нужен инструмент, ответь СТРОГО одним JSON-объектом, "
            "без markdown, без пояснений до и после, в формате:\n"
            '{"tool": "<имя_инструмента>", "args": {<параметры>}}\n'
            "Если инструмент НЕ нужен — ответь обычным текстом пользователю.\n"
            "После того как вернул JSON с инструментом, НИЧЕГО не дописывай и "
            "НЕ додумывай результат: я пришлю результат инструмента следующим "
            "сообщением, и только тогда формулируй ответ пользователю.\n"
        )

        examples = (  # обычный литерал: few-shot, критичный для локальных моделей
            "Примеры (формат Ответ — это ровно то, что ты должен вернуть):\n"
            "Пользователь: Запомни код от квартиры 4412\n"
            'Ответ: {"tool": "add_note", "args": {"content": "код от квартиры 4412"}}\n\n'
            "Пользователь: Какие у меня заметки?\n"
            'Ответ: {"tool": "list_notes", "args": {}}\n\n'
            "Пользователь: Который час в Токио?\n"
            'Ответ: {"tool": "get_current_time", "args": {"timezone": "Asia/Tokyo"}}\n\n'
            "Пользователь: Привет, как дела?\n"
            "Ответ: Привет! Всё по плану. Чем могу помочь?\n"
        )

        return header + protocol + contract + examples

    def _wire_history_native(self, rows: list[dict]) -> list[dict]:
        return rows

    def _wire_history_json(self, rows: list[dict]) -> list[dict]:
        return rows


    @staticmethod
    def _strip_code_fences(text: str) -> str:
        """Снимает обёртку ```lang ... ``` , если модель её добавила."""
        text = text.strip()
        if not text.startswith("```"):
            return text
        lines = text.splitlines()
        if lines and lines[0].startswith("```"):
            lines = lines[1:]
        if lines and lines[-1].strip().startswith("```"):
            lines = lines[:-1]
        return "\n".join(lines).strip()

    def _extract_json_tool_call(self, text: str) -> dict | None:
        """
        Двухпроходная эвристика.

        Проход 1: строгий json.loads от очищённого текста.
        Проход 2: если не удалось — вырезаем подстроку от первой '{' до
                  последней '}' и пробуем ещё раз (локальные модели любят
                  добавлять префикс/суффикс вокруг JSON).

        Инструментом считаем ТОЛЬКО словарь с непустым строковым "tool".
        Поэтому легитимный JSON-ответ пользователя без ключа "tool" (например
        {"a": 1}) парсером НЕ трактуется как вызов — он уйдёт как обычный текст.
        Возвращает {"name": str, "args": dict} или None.
        """
        if not text:
            return None

        cleaned = self._strip_code_fences(text)
        parsed = None
        try:
            parsed = json.loads(cleaned)
        except json.JSONDecodeError:
            start = cleaned.find("{")
            end = cleaned.rfind("}")
            if start != -1 and end > start:
                try:
                    parsed = json.loads(cleaned[start : end + 1])
                except json.JSONDecodeError:
                    parsed = None

        if not isinstance(parsed, dict):
            return None

        name = parsed.get("tool")
        if not isinstance(name, str) or not name.strip():
            return None

        args = parsed.get("args")
        if not isinstance(args, dict):
            logger.warning("Tool args not a dict, coercing to {} name=%s", name.strip())
            args = {}

        return {"name": name.strip(), "args": args}

    # ============================ главный вход ================================

    async def handle_user_message(self, user_id: str, chat_id: str, text: str) -> str:
        session_id = self.storage.get_or_create_active_session(user_id)
        self.storage.add_message(session_id, "user", text)

        rows = self.storage.get_recent_messages(
            session_id, limit=self.settings.history_limit
        )

        mode = (self.settings.tool_mode or "native").lower()
        if mode == "json":
            return await self._run_json_loop(user_id, chat_id, session_id, rows)
        return await self._run_native_loop(user_id, chat_id, session_id, rows)

    # ---------------------------- нативный цикл  -----------

    async def _run_native_loop(self, user_id: str, chat_id: str, session_id: int, rows: list[dict]) -> str:
        messages = [
            {"role": "system", "content": self._system_prompt_native()},
            *self._wire_history_native(rows),
        ]
        tool_definitions = self.tools.get_definitions()

        for step in range(self.settings.max_agent_steps):
            logger.info(
                "Native step=%d calling LLM model=%s messages=%d",
                step, self.settings.ollama_model, len(messages),
            )

            started_at = time.perf_counter()
            response = await self.llm_client.chat(messages=messages, tools=tool_definitions)
            elapsed = time.perf_counter() - started_at

            assistant_message = response.choices[0].message
            tool_calls = assistant_message.tool_calls or []

            logger.info(
                "Native step=%d LLM responded in %.2fs tool_calls=%d",
                step, elapsed, len(tool_calls),
            )

            # --- ГИБРИДНЫЙ FALLBACK ---
            # Если нативных вызовов нет, но модель выдала текст, который выглядит как JSON-вызов,
            # пытаемся распарсить его вручную. Это спасает от потери контекста.
            if not tool_calls and assistant_message.content:
                potential_call = self._extract_json_tool_call(assistant_message.content)
                
                if potential_call:
                    logger.warning(
                        "Native fallback triggered: parsed JSON from text content name=%s",
                        potential_call["name"]
                    )
                    
                    result = await self.tools.execute(
                        user_id=user_id,
                        chat_id=chat_id, 
                        name=potential_call["name"],
                        arguments=potential_call["args"]
                    )
                    
                    synthetic_msg = {
                        "role": "user",
                        "content": f"[SYSTEM_RESULT] Tool '{potential_call['name']}' executed successfully. Output:\n{result}"
                    }
                    messages.append(synthetic_msg)
                    
                    self.storage.add_message(
                        session_id=session_id,
                        role="assistant",
                        content=f"FALLBACK_EXECUTED:{potential_call['name']}",
                        tool_name=potential_call["name"],
                        tool_call_id=None
                    )
                    
                    continue 
            
            # --- КОНЕЦ FALLBACK ---

            if tool_calls:
                messages.append(assistant_message.model_dump())

                for tool_call in tool_calls:
                    name = tool_call.function.name
                    try:
                        arguments = json.loads(tool_call.function.arguments or "{}")
                    except json.JSONDecodeError:
                        logger.warning("Bad tool args JSON name=%s", name)
                        arguments = {}

                    logger.info("Native tool call step=%d name=%s args_count=%d",
                                step, name, len(arguments))
                    
                    # Выполняем нативный инструмент, ПРОКИДЫВАЕМ CHAT_ID
                    result = await self.tools.execute(
                        user_id=user_id, 
                        chat_id=chat_id, 
                        name=name, 
                        arguments=arguments
                    )
                    
                    logger.info("Native tool done step=%d name=%s result_chars=%d",
                                step, name, len(result))

                    messages.append({
                        "role": "tool",
                        "tool_call_id": tool_call.id,
                        "name": name,
                        "content": result,
                    })
                    self.storage.add_message(
                        session_id=session_id, role="tool", content=result,
                        tool_name=name, tool_call_id=tool_call.id,
                    )
                continue

            content = assistant_message.content or "Не смог сформулировать ответ."
            self.storage.add_message(session_id, "assistant", content)
            return content

        fallback = "Я сделал слишком много шагов и остановился. Попробуй упростить запрос."
        logger.warning("Native hit max steps=%d user_id=%s", self.settings.max_agent_steps, user_id)
        self.storage.add_message(session_id, "assistant", fallback)
        return fallback

    # ---------------------------- json-цикл ----------------------------------

    async def _run_json_loop(self, user_id: str, chat_id: str, session_id: int, rows: list[dict]) -> str:
        messages = [
            {"role": "system", "content": self._system_prompt_json()},
            *self._wire_history_json(rows),
        ]

        seen_signatures: set[tuple[str, str]] = set()

        for step in range(self.settings.max_agent_steps):
            logger.info(
                "Json step=%d calling LLM model=%s messages=%d",
                step, self.settings.ollama_model, len(messages),
            )

            started_at = time.perf_counter()
            response = await self.llm_client.chat(messages=messages, tools=None)
            elapsed = time.perf_counter() - started_at

            text = (response.choices[0].message.content or "").strip()
            call = self._extract_json_tool_call(text)

            logger.info(
                "Json step=%d LLM responded in %.2fs json_tool=%s",
                step, elapsed, call["name"] if call else "none",
            )

            if call is not None:
                name = call["name"]
                arguments = call["args"]

                signature = (name, json.dumps(arguments, sort_keys=True, ensure_ascii=False))
                if signature in seen_signatures:
                    content = "Похоже, я зациклился на одном действии. Уточни запрос, пожалуйста."
                    logger.warning("Json loop-guard tripped step=%d name=%s", step, name)
                    self.storage.add_message(session_id, "assistant", content)
                    return content
                seen_signatures.add(signature)

                logger.info("Json tool call step=%d name=%s args_count=%d",
                            step, name, len(arguments))
                
                # Выполняем инструмент из JSON-режима, ПРОКИДЫВАЕМ CHAT_ID
                result = await self.tools.execute(
                    user_id=user_id, 
                    chat_id=chat_id, 
                    name=name, 
                    arguments=arguments
                )
                
                logger.info("Json tool done step=%d name=%s result_chars=%d",
                            step, name, len(result))

                messages.append({"role": "assistant", "content": text})
                messages.append({
                    "role": "user",
                    "content": f"[tool_result] {name}: {result}",
                })
                self.storage.add_message(
                    session_id=session_id, role="tool", content=result,
                    tool_name=name, tool_call_id=None,
                )
                continue

            content = text or "Не смог сформулировать ответ."
            self.storage.add_message(session_id, "assistant", content)
            return content

        fallback = "Я сделал слишком много шагов и остановился. Попробуй упростить запрос."
        logger.warning("Json hit max steps=%d user_id=%s", self.settings.max_agent_steps, user_id)
        self.storage.add_message(session_id, "assistant", fallback)
        return fallback