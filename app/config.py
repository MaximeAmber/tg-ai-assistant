from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    telegram_bot_token: str
    llm_provider: str = "ollama"

    ollama_base_url: str = "http://localhost:11434/v1"
    ollama_model: str = "qwen2.5:7b-instruct"

    db_path: str = "assistant.db"
    log_level: str = "INFO"
    default_timezone: str = "Europe/Moscow"

    tool_mode: str = "native"
    max_agent_steps: int = 4
    history_limit: int = 20

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )