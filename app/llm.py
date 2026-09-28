from openai import AsyncOpenAI

from app.config import Settings


class LLMClient:
    def __init__(self, settings: Settings):
        self.settings = settings
        self.client = AsyncOpenAI(
            base_url=settings.ollama_base_url,
            api_key="ollama",
        )

    async def chat(
        self,
        messages: list[dict],
        tools: list[dict] | None = None,
    ):
        kwargs = {
            "model": self.settings.ollama_model,
            "messages": messages,
            "temperature": 0.2,
            "max_tokens": 700,
        }

        if tools:
            kwargs["tools"] = tools
            kwargs["tool_choice"] = "auto"

        return await self.client.chat.completions.create(**kwargs)