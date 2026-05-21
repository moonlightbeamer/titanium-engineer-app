"""WorkerContainer — lazily-initialized shared dependencies for Celery workers."""

from __future__ import annotations

import os
import ssl
import urllib.parse
from urllib.parse import parse_qs, urlencode, urlparse, urlunparse

from redis import Redis


def _make_redis_client(url: str, **kwargs) -> Redis:
    """Create a Redis client, stripping ssl_cert_reqs from the URL and passing it
    as ssl.CERT_NONE kwarg so redis-py 5.x string validation is bypassed."""
    if url.startswith("rediss://"):
        parsed = urlparse(url)
        params = {k: v for k, v in parse_qs(parsed.query, keep_blank_values=True).items()
                  if k != "ssl_cert_reqs"}
        url = urlunparse(parsed._replace(query=urlencode(params, doseq=True)))
        kwargs.setdefault("ssl_cert_reqs", ssl.CERT_NONE)
    return Redis.from_url(url, **kwargs)

from pr_reviewer.agents.llm import make_llm
from pr_reviewer.agents.review_agent import ReviewAgent
from pr_reviewer.components.comment_poster import CommentPoster
from pr_reviewer.components.diff_parser import DiffParser
from pr_reviewer.components.secret_scrubber import SecretScrubber
from pr_reviewer.config.loader import ConfigLoader
from pr_reviewer.config.schema import Config
from pr_reviewer.kb.knowledge_base import KnowledgeBase
from pr_reviewer.kb.mcp_client import MCPClient
from pr_reviewer.logging import get_logger
from pr_reviewer.store.db import get_engine
from pr_reviewer.store.feedback_store import FeedbackStore
from pr_reviewer.store.github_client import GitHubAPIClient
from pr_reviewer.store.job_store import JobStore
from pr_reviewer.workers.job_processor import JobProcessor

_logger = get_logger(__name__)


class _AzureEmbedder:
    """Thin wrapper around Azure OpenAI embeddings for ChromaDB query-time use."""

    def __init__(self) -> None:
        import openai
        self._client = openai.AzureOpenAI(
            api_key=os.environ["AZURE_OPENAI_API_KEY"],
            azure_endpoint=os.environ["AZURE_OPENAI_ENDPOINT"],
            api_version=os.getenv("AZURE_OPENAI_API_VERSION", "2024-08-01-preview"),
        )
        self._deployment = os.environ["AZURE_OPENAI_EMBEDDING_DEPLOYMENT"]

    def embed(self, text: str) -> list[float]:
        return self._client.embeddings.create(input=text, model=self._deployment).data[0].embedding


def _make_embedder() -> _AzureEmbedder | None:
    if os.getenv("AZURE_OPENAI_API_KEY") and os.getenv("AZURE_OPENAI_EMBEDDING_DEPLOYMENT"):
        return _AzureEmbedder()
    _logger.warning("AZURE_OPENAI_EMBEDDING_DEPLOYMENT not set; KB queries will use local embeddings")
    return None


class WorkerContainer:
    """Holds shared connections and creates per-installation processor instances."""

    def __init__(self) -> None:
        self._engine = get_engine()
        self._redis = _make_redis_client(
            os.getenv("REDIS_URL", "redis://localhost:6379/0"),
            decode_responses=True,
        )
        self.job_store = JobStore(self._engine)
        self._feedback_store = FeedbackStore(self._engine)
        self._diff_parser = DiffParser()
        self._secret_scrubber = SecretScrubber()

        # Import deferred to post-fork: chromadb loads hnswlib (native C++) at
        # import time, which is not fork-safe on macOS.
        import chromadb  # noqa: PLC0415

        chroma_url = os.getenv("CHROMADB_URL", "http://localhost:8001")
        parsed = urllib.parse.urlparse(chroma_url)
        self._chroma = chromadb.HttpClient(
            host=parsed.hostname or "localhost",
            port=parsed.port or 8001,
        )

        default_config = Config()
        embedder = _make_embedder()
        self._knowledge_base = KnowledgeBase(self._chroma, default_config, embedder=embedder)
        self._mcp_client = MCPClient(self._knowledge_base, default_config, self._redis)

        self._review_agent = ReviewAgent(make_llm())

        _logger.info("WorkerContainer initialised")

    def make_processor(self, installation_id: int) -> JobProcessor:
        github_client = GitHubAPIClient(
            installation_id=installation_id,
            redis_client=self._redis,
            app_id=os.environ["GITHUB_APP_ID"],
            private_key=os.environ["GITHUB_APP_PRIVATE_KEY"],
        )
        config_loader = ConfigLoader(github_client)
        comment_poster = CommentPoster(github_client)
        return JobProcessor(
            job_store=self.job_store,
            github_client=github_client,
            diff_parser=self._diff_parser,
            config_loader=config_loader,
            feedback_store=self._feedback_store,
            review_agent=self._review_agent,
            comment_poster=comment_poster,
            secret_scrubber=self._secret_scrubber,
            knowledge_base=self._knowledge_base,
            mcp_client=self._mcp_client,
        )


_instance: WorkerContainer | None = None


def get_container() -> WorkerContainer:
    """Return the process-level singleton container, initialising it on first call."""
    global _instance
    if _instance is None:
        _instance = WorkerContainer()
    return _instance
