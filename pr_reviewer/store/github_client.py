"""GitHub API client with JWT auth, Redis token caching, and OTel instrumentation."""

import json
import time
from datetime import UTC, datetime, timedelta
from typing import Any

import httpx
import jwt
from opentelemetry import trace
from redis import Redis

from pr_reviewer.logging import get_logger

_logger = get_logger(__name__)
_tracer = trace.get_tracer(__name__)

_REFRESH_BEFORE_EXPIRY = timedelta(minutes=4)
_JWT_LIFETIME_SECONDS = 60
_TOKEN_CACHE_TTL_SECONDS = 3300  # store for 55 min; GitHub tokens last 1 hour
_MAX_RETRIES = 3


class AuthError(Exception):
    pass


class RateLimitError(Exception):
    pass


class GitHubAPIClient:
    BASE_URL = "https://api.github.com"

    def __init__(
        self,
        installation_id: int,
        redis_client: Redis,
        app_id: str,
        private_key: str,
        http_client: httpx.Client | None = None,
    ) -> None:
        self._installation_id = installation_id
        self._redis = redis_client
        self._app_id = app_id
        self._private_key = private_key
        self._http = http_client or httpx.Client(base_url=self.BASE_URL)

    # ── Auth ──────────────────────────────────────────────────────────────────

    def _generate_jwt(self) -> str:
        now = int(time.time())
        return jwt.encode(
            {"iat": now, "exp": now + _JWT_LIFETIME_SECONDS, "iss": self._app_id},
            self._private_key,
            algorithm="RS256",
        )

    def _cache_key(self) -> str:
        return f"gh_token:{self._installation_id}"

    def get_access_token(self) -> str:
        key = self._cache_key()
        cached = self._redis.get(key)
        if cached:
            data = json.loads(cached)
            expires_at = datetime.fromisoformat(data["expires_at"])
            if expires_at - datetime.now(UTC) > _REFRESH_BEFORE_EXPIRY:
                return data["token"]  # type: ignore[return-value]

        jwt_token = self._generate_jwt()
        response = self._request(
            "POST",
            f"/app/installations/{self._installation_id}/access_tokens",
            headers={"Authorization": f"Bearer {jwt_token}"},
        )
        payload = response.json()
        token: str = payload["token"]
        expires_at: str = payload["expires_at"]

        self._redis.setex(
            key,
            _TOKEN_CACHE_TTL_SECONDS,
            json.dumps({"token": token, "expires_at": expires_at}),
        )
        return token

    # ── Core request ─────────────────────────────────────────────────────────

    def _request(
        self,
        method: str,
        path: str,
        headers: dict[str, str] | None = None,
        **kwargs: Any,
    ) -> httpx.Response:
        with _tracer.start_as_current_span("github.api") as span:
            url = f"{self.BASE_URL}{path}"
            span.set_attribute("endpoint", url)

            merged: dict[str, str] = {
                "Accept": "application/vnd.github.v3+json",
                **(headers or {}),
            }
            # Inject W3C traceparent
            ctx = trace.get_current_span().get_span_context()
            if ctx.is_valid:
                trace_id = format(ctx.trace_id, "032x")
                span_id = format(ctx.span_id, "016x")
                flags = format(ctx.trace_flags, "02x")
                merged["traceparent"] = f"00-{trace_id}-{span_id}-{flags}"

            for attempt in range(1, _MAX_RETRIES + 1):
                response = self._http.request(method, path, headers=merged, **kwargs)
                span.set_attribute("status_code", response.status_code)

                if response.status_code == 401:
                    raise AuthError(f"GitHub API auth failed (401) on {path}")

                if response.status_code in (403, 429):
                    retry_after = int(response.headers.get("Retry-After", "1"))
                    if attempt >= _MAX_RETRIES:
                        raise RateLimitError(
                            f"Rate limited on {path} after {_MAX_RETRIES} attempts"
                        )
                    _logger.warning(
                        f"Rate limited ({response.status_code}); retry in {retry_after}s"
                    )
                    time.sleep(retry_after)
                    continue

                response.raise_for_status()
                return response

        raise RateLimitError(f"Rate limited on {path} after {_MAX_RETRIES} attempts")

    # ── Public API methods ───────────────────────────────────────────────────

    def get_diff(self, repo: str, pr_number: int) -> str:
        token = self.get_access_token()
        response = self._request(
            "GET",
            f"/repos/{repo}/pulls/{pr_number}",
            headers={
                "Authorization": f"token {token}",
                "Accept": "application/vnd.github.v3.diff",
            },
        )
        return response.text

    def get_file_content(self, repo: str, path: str, ref: str) -> str:
        import base64

        token = self.get_access_token()
        response = self._request(
            "GET",
            f"/repos/{repo}/contents/{path}",
            headers={"Authorization": f"token {token}"},
            params={"ref": ref},
        )
        return base64.b64decode(response.json()["content"]).decode("utf-8")

    def list_directory(self, repo: str, path: str, ref: str) -> list[str]:
        token = self.get_access_token()
        response = self._request(
            "GET",
            f"/repos/{repo}/contents/{path}",
            headers={"Authorization": f"token {token}"},
            params={"ref": ref},
        )
        return [item["name"] for item in response.json()]

    def get_symbol_usages(self, repo: str, symbol: str) -> list[dict]:
        token = self.get_access_token()
        response = self._request(
            "GET",
            "/search/code",
            headers={"Authorization": f"token {token}"},
            params={"q": f"{symbol} repo:{repo}"},
        )
        return response.json().get("items", [])  # type: ignore[return-value]

    def post_review(
        self,
        repo: str,
        pr_number: int,
        body: str,
        event: str,
        comments: list[dict],
    ) -> dict:
        token = self.get_access_token()
        response = self._request(
            "POST",
            f"/repos/{repo}/pulls/{pr_number}/reviews",
            headers={"Authorization": f"token {token}"},
            json={"body": body, "event": event, "comments": comments},
        )
        return response.json()  # type: ignore[return-value]

    def get_existing_reviews(self, repo: str, pr_number: int) -> list[dict]:
        token = self.get_access_token()
        response = self._request(
            "GET",
            f"/repos/{repo}/pulls/{pr_number}/reviews",
            headers={"Authorization": f"token {token}"},
        )
        return response.json()  # type: ignore[return-value]

    def compare_commits(self, repo: str, base: str, head: str) -> dict:
        token = self.get_access_token()
        response = self._request(
            "GET",
            f"/repos/{repo}/compare/{base}...{head}",
            headers={"Authorization": f"token {token}"},
        )
        return response.json()  # type: ignore[return-value]

    def get_branch_head_sha(self, repo: str, branch: str) -> str:
        token = self.get_access_token()
        response = self._request(
            "GET",
            f"/repos/{repo}/git/refs/heads/{branch}",
            headers={"Authorization": f"token {token}"},
        )
        return response.json()["object"]["sha"]  # type: ignore[return-value]
