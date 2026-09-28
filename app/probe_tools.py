import asyncio
import json

from app.config import Settings
from app.llm import LLMClient
from app.storage import Storage
from app.tools import ToolRegistry


async def run_case(llm, tools, title, messages):
    print(f"--- {title} ---")
    try:
        response = await llm.chat(messages=messages, tools=tools.get_definitions())
        message = response.choices[0].message
        calls = message.tool_calls or []
        print("tool_calls =", len(calls))
        for call in calls:
            print("  name =", call.function.name,
                  "args =", call.function.arguments)
        if not calls:
            print("  content_repr =", repr((message.content or "")[:200]))
    except Exception as exc:
        # Битая история может дать и явную ошибку валидации у эндпоинта.
        # Это тоже подтверждение гипотезы, просто в другой форме.
        print("EXCEPTION =", type(exc).__name__, str(exc)[:300])
    print()


async def main() -> None:
    settings = Settings()
    storage = Storage(settings.db_path)
    llm = LLMClient(settings)
    tools = ToolRegistry(storage=storage, default_timezone=settings.default_timezone)

    system = {"role": "system", "content": "Ты ассистент. Используй инструменты, когда нужно."}

    # Кейс 1: чистая история (как раньше) — ожидаем tool_calls=1.
    case_clean = [
        system,
        {"role": "user", "content": "Который час в Токио?"},
    ]

    # Кейс 2: воспроизводим битую межтуровую историю — tool без парного
    # assistant.tool_calls, ровно то, что пишет наш цикл в SQLite.
    case_broken = [
        system,
        {"role": "user", "content": "Запомни код от квартиры 4412"},
        {"role": "tool", "tool_call_id": "call_fake_1", "name": "add_note",
         "content": "Note saved."},
        {"role": "assistant", "content": "Сохранил заметку."},
        {"role": "user", "content": "Который час в Токио?"},
    ]

    await run_case(llm, tools, "CASE 1 clean history", case_clean)
    await run_case(llm, tools, "CASE 2 broken history", case_broken)


if __name__ == "__main__":
    asyncio.run(main())