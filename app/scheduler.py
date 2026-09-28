import asyncio
import logging
from datetime import datetime, timezone

from aiogram import Bot

from app.storage import Storage

logger = logging.getLogger(__name__)


class ReminderScheduler:
    def __init__(self, storage: Storage, bot: Bot):
        self.storage = storage
        self.bot = bot
        self._running = False

    async def start(self) -> None:
        """Запускает бесконечный цикл проверки."""
        self._running = True
        logger.info("Reminder scheduler started.")
        
        while self._running:
            try:
                await self._check_and_send()
            except Exception as exc:
                # Ошибка отправки одного сообщения не должна убивать весь планировщик
                logger.exception("Error in scheduler loop")
            
            # Ждем 30 секунд перед следующей проверкой
            await asyncio.sleep(30)

    async def stop(self) -> None:
        """Останавливает планировщик (для graceful shutdown)."""
        self._running = False
        logger.info("Reminder scheduler stopped.")

    async def _check_and_send(self) -> None:
        now_utc = datetime.now(timezone.utc).isoformat()

        with self.storage.connection() as conn:
            # Ищем все pending-напоминания, срок которых наступил
            rows = conn.execute(
                """
                SELECT id, chat_id, text 
                FROM reminders 
                WHERE status = 'pending' AND due_at <= ?
                ORDER BY due_at ASC
                """,
                (now_utc,),
            ).fetchall()

            if not rows:
                return

            logger.info("Found %d overdue reminder(s). Sending...", len(rows))

            for row in rows:
                try:
                    # Активная отправка сообщения пользователю
                    await self.bot.send_message(
                        chat_id=row["chat_id"],
                        text=f"⏰ Напоминание: {row['text']}"
                    )
                    
                    # Помечаем как выполненное
                    conn.execute(
                        "UPDATE reminders SET status = 'sent', sent_at = ? WHERE id = ?",
                        (now_utc, row["id"]),
                    )
                    logger.info("Sent reminder #%s to chat %s", row["id"], row["chat_id"])
                    
                except Exception as exc:
                    # Если Telegram недоступен или ID чата неверный — логируем и идем дальше
                    logger.error("Failed to send reminder #%s: %s", row["id"], exc)