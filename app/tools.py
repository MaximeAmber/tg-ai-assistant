import json
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

from app.storage import Storage


class ToolRegistry:
    def __init__(self, storage: Storage, default_timezone: str):
        self.storage = storage
        self.default_timezone = default_timezone

        _TZ_ALIASES = {
            "tokyo": "Asia/Tokyo", "токио": "Asia/Tokyo", "japan": "Asia/Tokyo",
            "london": "Europe/London", "лондон": "Europe/London", "uk": "Europe/London",
            "new_york": "America/New_York", "нью_йорк": "America/New_York",
            "nyc": "America/New_York", "ny": "America/New_York",
            "berlin": "Europe/Berlin", "берлин": "Europe/Berlin",
            "paris": "Europe/Paris", "париж": "Europe/Paris",
            "dubai": "Asia/Dubai", "дубай": "Asia/Dubai",
            "sydney": "Australia/Sydney", "сидней": "Australia/Sydney",
            "moscow": "Europe/Moscow", "москва": "Europe/Moscow",
            "utc": "UTC", "gmt": "UTC",
        }

    # --- нативные схемы (для TOOL_MODE=native) ---
    def get_definitions(self) -> list[dict]:
        return [
            {
                "type": "function",
                "function": {
                    "name": "get_current_time",
                    "description": "Get current date and time, optionally in a specific timezone",
                    "parameters": {
                        "type": "object",
                        "properties": {
                            "timezone": {
                                "type": "string",
                                "description": "IANA timezone, e.g. Europe/Moscow or Asia/Tokyo",
                            }
                        },
                        "required": [],
                    },
                },
            },
            {
                "type": "function",
                "function": {
                    "name": "add_note",
                    "description": "Save a personal note for the current user",
                    "parameters": {
                        "type": "object",
                        "properties": {
                            "content": {
                                "type": "string",
                                "description": "Note text to save",
                            }
                        },
                        "required": ["content"],
                    },
                },
            },
            {
                "type": "function",
                "function": {
                    "name": "list_notes",
                    "description": "List recent personal notes for the current user",
                    "parameters": {
                        "type": "object",
                        "properties": {
                            "limit": {
                                "type": "integer",
                                "description": "Maximum number of notes to return",
                            }
                        },
                        "required": [],
                    },
                },
            },
            # --- ИНСТРУМЕНТЫ ДЛЯ НАПОМИНАНИЙ ---
            {
                "type": "function",
                "function": {
                    "name": "add_reminder",
                    "description": "Set a reminder to notify the user at a specific future time.",
                    "parameters": {
                        "type": "object",
                        "properties": {
                            "text": {"type": "string", "description": "The message to send later"},
                            "due_minutes_from_now": {
                                "type": "integer",
                                "description": "How many minutes from now to trigger this reminder"
                            }
                        },
                        "required": ["text", "due_minutes_from_now"]
                    }
                }
            },
            {
                "type": "function",
                "function": {
                    "name": "list_reminders",
                    "description": "List all pending reminders for the user.",
                    "parameters": {"type": "object", "properties": {}, "required": []}
                }
            },
            {
                "type": "function",
                "function": {
                    "name": "cancel_reminder",
                    "description": "Cancel a scheduled reminder by its ID.",
                    "parameters": {
                        "type": "object",
                        "properties": {
                            "reminder_id": {"type": "integer", "description": "ID of the reminder to cancel"}
                        },
                        "required": ["reminder_id"]
                    }
                }
            }
        ]

    # --- текстовая спецификация (для TOOL_MODE=json) ---
    def get_json_protocol_spec(self) -> str:
        lines = ["Доступные инструменты:"]
        for definition in self.get_definitions():
            fn = definition["function"]
            name = fn["name"]
            desc = fn.get("description", "")
            params = fn.get("parameters", {}).get("properties", {})
            required = set(fn.get("parameters", {}).get("required", []))

            if params:
                rendered = []
                for pname, pmeta in params.items():
                    ptype = pmeta.get("type", "any")
                    pdesc = pmeta.get("description", "")
                    req = "обязателен" if pname in required else "опционален"
                    rendered.append(f"{pname} ({ptype}, {req}{': ' + pdesc if pdesc else ''})")
                params_text = "; ".join(rendered)
            else:
                params_text = "параметров нет"

            lines.append(f"- {name}: {desc}. Параметры: {params_text}.")
        return "\n".join(lines) + "\n"

    # --- исполнение (общее для обоих режимов) ---
    async def execute(self, user_id: str, chat_id: str, name: str, arguments: dict) -> str:
        """
        ВАЖНО: Теперь принимает chat_id для работы напоминаний.
        """
        if name == "get_current_time":
            return self._get_current_time(arguments)
        if name == "add_note":
            return self._add_note(user_id, arguments)
        if name == "list_notes":
            return self._list_notes(user_id, arguments)
        
        # --- ДИСПАТЧЕР НАПОМИНАНИЙ ---
        if name == "add_reminder":
            return self._add_reminder(user_id, chat_id, arguments)
        if name == "list_reminders":
            return self._list_reminders(user_id)
        if name == "cancel_reminder":
            return self._cancel_reminder(user_id, arguments)

        return f"Unknown tool: {name}"

    # --- РЕАЛИЗАЦИЯ ЧАСОВ (с алиасами из прошлого шага) ---
    def _resolve_timezone(self, raw):
        if not raw or not str(raw).strip():
            return None, None

        name = str(raw).strip()
        try:
            return ZoneInfo(name), name
        except Exception:
            pass

        key = name.lower().replace(" ", "_").replace("-", "_")
        for junk in ("timezone_", "tz_", "zone_", "часовой_пояс_", "пояс_"):
            if key.startswith(junk):
                key = key[len(junk):]

        alias = getattr(self, '_TZ_ALIASES', {}).get(key) # Безопасный доступ к атрибуту класса
        if alias:
            try:
                return ZoneInfo(alias), alias
            except Exception:
                pass

        return None, name

    def _get_current_time(self, arguments: dict) -> str:
        tz_obj, resolved = self._resolve_timezone(arguments.get("timezone"))

        if tz_obj is None and resolved is None:
            return (
                "timezone не указан. Если пользователь спросил про конкретный город "
                "или пояс — укажи IANA-зону (например Asia/Tokyo). Если про локальное "
                f"время пользователя — используй {self.default_timezone}."
            )

        if tz_obj is None:
            return (
                f"Не удалось распознать часововой пояс: {resolved}. "
                "Используй IANA-формат, например Asia/Tokyo, Europe/London, "
                "America/New_York, Europe/Moscow."
            )

        now = datetime.now(tz_obj)
        return f"{now.strftime('%Y-%m-%d %H:%M:%S %Z')} ({resolved})"

    # --- ЗАМЕТКИ ---
    def _add_note(self, user_id: str, arguments: dict) -> str:
        content = str(arguments.get("content", "")).strip()
        if not content:
            return "Note content is empty."
        with self.storage.connection() as conn:
            conn.execute(
                "INSERT INTO notes (user_id, content) VALUES (?, ?)",
                (user_id, content),
            )
        return "Note saved."

    def _list_notes(self, user_id: str, arguments: dict) -> str:
        limit = int(arguments.get("limit") or 10)
        limit = max(1, min(limit, 50))
        with self.storage.connection() as conn:
            rows = conn.execute(
                """
                SELECT id, content, created_at
                FROM notes
                WHERE user_id = ?
                ORDER BY id DESC
                LIMIT ?
                """,
                (user_id, limit),
            ).fetchall()
        if not rows:
            return "No notes found."
        return "\n".join(
            f"{row['id']}. {row['content']} ({row['created_at']})" for row in rows
        )

    # --- НАПОМИНАНИЯ ---
    
    def _add_reminder(self, user_id: str, chat_id: str, arguments: dict) -> str:
        text = str(arguments.get("text", "")).strip()
        minutes = int(arguments.get("due_minutes_from_now", 0))
        
        if not text:
            return "Ошибка: текст напоминания пустой."
        if minutes <= 0:
            return "Ошибка: количество минут должно быть больше 0."
            
        # Считаем время дедлайна в UTC (для единообразия с планировщиком)
        # Но сохраняем удобочитаемый формат для юзера
        now_utc = datetime.utcnow()
        due_dt_utc = now_utc + timedelta(minutes=minutes)
        
        # Для отображения пользователю переводим в его зону
        local_tz = ZoneInfo(self.default_timezone)
        display_due = due_dt_utc.replace(tzinfo=ZoneInfo('UTC')).astimezone(local_tz)

        with self.storage.connection() as conn:
            conn.execute(
                """
                INSERT INTO reminders (user_id, chat_id, text, due_at, status)
                VALUES (?, ?, ?, ?, 'pending')
                """,
                (user_id, chat_id, text, due_dt_utc.isoformat()),
            )
            
        return f"✅ Напоминание установлено на {display_due.strftime('%H:%M')} ({minutes} мин.). Текст: '{text}'"

    def _list_reminders(self, user_id: str) -> str:
        with self.storage.connection() as conn:
            rows = conn.execute(
                """
                SELECT id, text, due_at, status
                FROM reminders
                WHERE user_id = ? AND status = 'pending'
                ORDER BY due_at ASC
                """,
                (user_id,),
            ).fetchall()
            
        if not rows:
            return "У вас нет активных напоминаний."
            
        local_tz = ZoneInfo(self.default_timezone)
        lines = []
        for row in rows:
            # Парсим ISO строку обратно в datetime для красивого вывода
            dt_utc = datetime.fromisoformat(row['due_at'])
            dt_local = dt_utc.replace(tzinfo=ZoneInfo('UTC')).astimezone(local_tz)
            time_str = dt_local.strftime("%d.%m %H:%M")
            lines.append(f"[{row['id']}] ⏰ {time_str} | {row['text']}")
            
        return "\n".join(lines)

    def _cancel_reminder(self, user_id: str, arguments: dict) -> str:
        rem_id = int(arguments.get("reminder_id", 0))
        if not rem_id:
            return "Ошибка: не указан ID напоминания."
            
        with self.storage.connection() as conn:
            cursor = conn.execute(
                """
                UPDATE reminders SET status = 'cancelled'
                WHERE id = ? AND user_id = ? AND status = 'pending'
                """,
                (rem_id, user_id),
            )
            
        if cursor.rowcount > 0:
            return f"❌ Напоминание #{rem_id} отменено."
        else:
            return f"Напоминание #{rem_id} не найдено или уже выполнено/отменено."