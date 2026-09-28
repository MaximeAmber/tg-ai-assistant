# Personal AI Assistant (Telegram + Local Qwen)

Первая версия персонального AI-ассистента в Telegram, работающего локально на Qwen 2.5 через Ollama.

Реализовано:
- Построение агентного цикла с tool calling.
- Управление контекстом и памятью диалога.
- Абстракция над LLM-провайдером (OpenAI-compatible API).
- Проактивное поведение (планировщик напоминаний).
- Чистая модульная архитектура (transport independent core).

Возможности

| Функция | Пример запроса | Инструмент |
|---------|----------------|------------|
| 💬 Диалог с памятью | «Имя пользователя, возраст и тд» | Context Window |
| 📝 Заметки | «Запомни...» | `add_note`, `list_notes` |
| ⏰ Время в поясах | «Который час в..?» | `get_current_time` |
| 🔔 Напоминания | «Напомни мне...» | `add_reminder`, Scheduler |

Все данные хранятся локально в SQLite. Никаких внешних облачных API для LLM.

## 🏗 Архитектура

```mermaid
graph TD
    TG[Telegram User] --> Bot[Aiogram Adapter]
    Bot --> Agent[AgentService Core]
    
    subgraph "Core Logic"
        Agent --> Loop{Agent Loop}
        Loop --> Tools[Tool Registry]
        Loop --> Mem[Session Memory]
    end
    
    Tools --> DB[(SQLite Storage)]
    Mem --> DB
    
    Agent --> LLM[LLM Client Abstraction]
    LLM --> Ollama[Ollama API localhost:11434]
    Ollama --> Model[Qwen2.5 Instruct]
    
    Sched[Async Scheduler] --> DB
    Sched --> Bot
