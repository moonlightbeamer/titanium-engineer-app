"""LLM factory — builds the ReviewAgent LLM client from environment variables.

Priority order:
  1. Azure OpenAI             (AZURE_OPENAI_API_KEY + AZURE_OPENAI_ENDPOINT)
  2. Azure AI Foundry Claude  (AZURE_ANTHROPIC_API_KEY + AZURE_ANTHROPIC_ENDPOINT)
  3. NoopLLM stub             (no credentials configured)
"""

import os
from typing import Any

from pr_reviewer.logging import get_logger

_logger = get_logger(__name__)


class _AzureAnthropicLLM:
    """Azure AI Foundry Claude adapter via litellm."""

    def __init__(self) -> None:
        self._api_key = os.environ["AZURE_ANTHROPIC_API_KEY"]
        endpoint = os.environ["AZURE_ANTHROPIC_ENDPOINT"].rstrip("/")
        self._api_base = f"{endpoint}/models"
        model_name = os.getenv("AZURE_ANTHROPIC_MODEL", "claude-3-5-sonnet-20241022")
        self._model = f"azure_ai/{model_name}"
        _logger.info(f"LLM: Azure AI Foundry Claude ({model_name})")

    def invoke(self, messages: list) -> Any:
        import litellm

        chat_messages = [{"role": "user", "content": m.content} for m in messages]
        return litellm.completion(
            model=self._model,
            messages=chat_messages,
            api_key=self._api_key,
            api_base=self._api_base,
        )


class _AzureOpenAILLM:
    """Azure OpenAI adapter."""

    def __init__(self) -> None:
        import openai

        self._client = openai.AzureOpenAI(
            api_key=os.environ["AZURE_OPENAI_API_KEY"],
            azure_endpoint=os.environ["AZURE_OPENAI_ENDPOINT"],
            api_version=os.getenv("AZURE_OPENAI_API_VERSION", "2024-08-01-preview"),
        )
        self._deployment = os.environ["AZURE_OPENAI_DEPLOYMENT_NAME"]
        _logger.info(f"LLM: Azure OpenAI ({self._deployment})")

    def invoke(self, messages: list) -> Any:
        oai_messages = [
            {"role": getattr(m, "role", "user"), "content": m.content}
            for m in messages
        ]
        return self._client.chat.completions.create(
            model=self._deployment,
            messages=oai_messages,
        )


class _NoopLLM:
    """Stub used when no LLM credentials are configured."""

    def invoke(self, messages: list) -> None:
        _logger.warning("No LLM configured; returning empty response")
        return None


def make_llm() -> Any:
    """Return the configured LLM. Priority: Azure OpenAI → Azure Anthropic → Noop."""
    if os.getenv("AZURE_OPENAI_API_KEY") and os.getenv("AZURE_OPENAI_ENDPOINT"):
        return _AzureOpenAILLM()
    if os.getenv("AZURE_ANTHROPIC_API_KEY") and os.getenv("AZURE_ANTHROPIC_ENDPOINT"):
        return _AzureAnthropicLLM()
    _logger.warning("No LLM credentials set; review agent will produce no findings")
    return _NoopLLM()
