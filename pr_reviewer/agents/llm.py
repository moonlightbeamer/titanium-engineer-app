"""LLM factory — builds the ReviewAgent LLM client from environment variables."""

import os
from typing import Any

from pr_reviewer.logging import get_logger

_logger = get_logger(__name__)


class _AzureOpenAILLM:
    """Azure OpenAI adapter that maps _Message list → chat completion."""

    def __init__(self) -> None:
        import openai

        self._client = openai.AzureOpenAI(
            api_key=os.environ["AZURE_OPENAI_API_KEY"],
            azure_endpoint=os.environ["AZURE_OPENAI_ENDPOINT"],
            api_version=os.getenv("AZURE_OPENAI_API_VERSION", "2024-08-01-preview"),
        )
        self._deployment = os.environ["AZURE_OPENAI_DEPLOYMENT_NAME"]

    def invoke(self, messages: list) -> Any:
        oai_messages = [{"role": "user", "content": m.content} for m in messages]
        return self._client.chat.completions.create(
            model=self._deployment,
            messages=oai_messages,
        )


class _NoopLLM:
    """Stub used when Azure OpenAI credentials are absent."""

    def invoke(self, messages: list) -> None:
        _logger.warning("No LLM configured; returning empty response")
        return None


def make_llm() -> Any:
    """Return the configured LLM. Falls back to a no-op stub if credentials are absent."""
    if os.getenv("AZURE_OPENAI_API_KEY") and os.getenv("AZURE_OPENAI_ENDPOINT"):
        return _AzureOpenAILLM()
    _logger.warning("Azure OpenAI credentials not set; review agent will return no findings")
    return _NoopLLM()
