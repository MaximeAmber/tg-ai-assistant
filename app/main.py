import asyncio
import logging

from aiogram import Bot, Dispatcher, F, Router
from aiogram.filters import Command
from aiogram.types import Message

from app.agent import AgentService
from app.config import Settings
from app.llm import LLMClient
from app.scheduler import ReminderScheduler  
from app.storage import Storage
from app.tools import ToolRegistry

# Настройка логирования
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(name)s %(message)s",
)
logger = logging.getLogger(__name__)

router = Router()


# --- ФАБРИКА ЗАВИСИМОСТЕЙ  ---
def create_dependencies(settings: Settings):
    """
    Создает экземпляры всех компонентов системы.
    Вынесено отдельно для удобства тестирования и чистоты main().
    """
    storage = Storage(settings.db_path)
    llm_client = LLMClient(settings)
    tools = ToolRegistry(storage=storage, default_timezone=settings.default_timezone)
    
    agent = AgentService(
        settings=settings,
        storage=storage,
        llm_client=llm_client,
        tools=tools,
    )
    
    return storage, agent


# --- TELEGRAM HANDLERS ---

@router.message(Command("start"))
async def cmd_start(message: Message) -> None:
    await message.answer(
        "Привет! Я твой персональный AI-ассистент на локальной Qwen.\n"
        "Я умею запоминать заметки, говорить время в любом поясе и ставить напоминания.\n\n"
        "Команды:\n"
        "/reset — начать новую сессию\n"
        "/help — справка"
    )


@router.message(Command("help"))
async def cmd_help(message: Message) -> None:
    help_text = (
        "<b>Что я умею:</b>\n\n"
        "📝 <b>Заметки</b>: «Запомни код от двери 1234», «Какие у меня заметки?»\n"
        "⏰ <b>Время</b>: «Который час в Нью-Йорке?», «Сколько сейчас времени?»\n"
        "🔔 <b>Напоминания</b>: «Напомни мне выпить воды через 5 минут»\n\n"
        "<i>Все данные хранятся локально в SQLite.</i>"
    )
    await message.answer(help_text, parse_mode="HTML")


@router.message(Command("reset"))
async def cmd_reset(message: Message, agent: AgentService) -> None:
    user_id = str(message.from_user.id)
    agent.storage.reset_session(user_id)
    await message.answer("✅ Сессия сброшена. Начинаем заново.")


@router.message(F.text)
async def handle_text(message: Message, agent: AgentService) -> None:
    if not message.text:
        return

    user_id = str(message.from_user.id)
    chat_id = str(message.chat.id)  

    try:
        answer = await agent.handle_user_message(user_id, chat_id, message.text)
        await message.answer(answer)
    except Exception:
        logger.exception("Error while handling message")
        await message.answer("❌ Упс, внутренняя ошибка агента. Попробуй ещё раз.")


# --- MAIN ENTRY POINT ---

async def main() -> None:
    settings = Settings()
    
    # Инициализация зависимостей через фабрику
    storage, agent = create_dependencies(settings)

    bot = Bot(token=settings.telegram_bot_token)
    dp = Dispatcher()
    
    # Передаем агента в контекст диспетчера (aiogram magic filter)
    dp["agent"] = agent
    dp.include_router(router)

    # Создаем экземпляр планировщика напоминаний
    scheduler = ReminderScheduler(storage=storage, bot=bot)

    logger.info("Starting Telegram bot + Scheduler with local Qwen via Ollama...")
    
    # Запускаем поллинг и планировщик ПАРАЛЛЕЛЬНО
    try:
        await asyncio.gather(
            dp.start_polling(bot),       # Task 1: Слушаем Telegram
            scheduler.start(),           # Task 2: Тикаем по базе каждые 30 сек
        )
    finally:
        # Graceful shutdown при остановке процесса (Ctrl+C)
        await scheduler.stop()
        await bot.session.close()
        logger.info("Bot stopped gracefully.")


if __name__ == "__main__":
    asyncio.run(main())