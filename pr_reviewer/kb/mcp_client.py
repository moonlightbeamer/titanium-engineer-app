"""MCPClient — thin HTTP client for NVD/OSV MCP servers with rate limiting and fallback."""

import secrets
import time
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any

import httpx
from opentelemetry import trace

from pr_reviewer.logging import get_logger

if TYPE_CHECKING:
    from pr_reviewer.config.schema import Config
    from pr_reviewer.kb.knowledge_base import KnowledgeBase

_logger = get_logger(__name__)

NVD_RATE_LIMIT = 10   # requests per minute
OSV_RATE_LIMIT = 20   # requests per minute

SNYK_RATE_LIMIT = 20

_SERVER_RATE_LIMITS: dict[str, int] = {
    "nvd": NVD_RATE_LIMIT,
    "osv": OSV_RATE_LIMIT,
    "snyk": SNYK_RATE_LIMIT,
    "ghsa": 30,
}


@dataclass(frozen=True)
class CVEAdvisory:
    id: str
    description: str
    severity: str
    source: str = "nvd"


@dataclass(frozen=True)
class OWASPMatch:
    category: str   # e.g. "A03:2021"
    description: str
    confidence: str  # "high" | "medium" | "low"


@dataclass(frozen=True)
class EscalationResult:
    reason: str
    cve_id: str | None = None


def _build_traceparent() -> str:
    span = trace.get_current_span()
    ctx = span.get_span_context()
    if ctx.is_valid:
        return f"00-{ctx.trace_id:032x}-{ctx.span_id:016x}-{ctx.trace_flags:02x}"
    return f"00-{secrets.token_hex(16)}-{secrets.token_hex(8)}-00"


class MCPClient:
    def __init__(
        self,
        knowledge_base: "KnowledgeBase",
        config: "Config",
        redis_client: Any,
    ) -> None:
        self._kb = knowledge_base
        self._config = config
        self._redis = redis_client

    def _check_rate_limit(self, server: str) -> bool:
        """Returns True if the call should proceed; False if the bucket is exhausted."""
        limit = _SERVER_RATE_LIMITS.get(server, 10)
        bucket = int(time.time() / 60)
        key = f"mcp:rate_limit:{server}:{bucket}"
        count = self._redis.incr(key)
        if count == 1:
            self._redis.expire(key, 120)
        return count <= limit

    def _headers(self) -> dict[str, str]:
        return {"traceparent": _build_traceparent()}

    def _fallback_to_kb(self, cve_id: str) -> "CVEAdvisory | EscalationResult":
        entries = self._kb.query(cve_id, category="security", language="")
        if not entries:
            return EscalationResult(
                reason="could not verify against live CVE data",
                cve_id=cve_id,
            )
        entry = entries[0]
        return CVEAdvisory(
            id=cve_id,
            description=entry.content,
            severity="unknown",
            source="fallback_corpus",
        )

    def lookup_cve(self, cve_id: str) -> "CVEAdvisory | EscalationResult":
        if not self._check_rate_limit("nvd"):
            _logger.warning(f"NVD rate limit exhausted — falling back to corpus for {cve_id}")
            return self._fallback_to_kb(cve_id)

        endpoint = self._config.mcp_servers.nvd
        url = f"{endpoint}/rest/json/cves/2.0"
        try:
            with httpx.Client() as client:
                response = client.get(
                    url,
                    params={"cveId": cve_id},
                    headers=self._headers(),
                )
                response.raise_for_status()
                data = response.json()
                description = ""
                severity = "unknown"
                vulns = data.get("vulnerabilities", [])
                if vulns:
                    cve_data = vulns[0].get("cve", {})
                    descs = cve_data.get("descriptions", [])
                    for d in descs:
                        if d.get("lang") == "en":
                            description = d.get("value", "")
                            break
                    metrics = cve_data.get("metrics", {})
                    cvss_v3 = metrics.get("cvssMetricV31", []) or metrics.get("cvssMetricV30", [])
                    if cvss_v3:
                        severity = cvss_v3[0].get("cvssData", {}).get("baseSeverity", "unknown")
                return CVEAdvisory(
                    id=cve_id, description=description, severity=severity, source="nvd"
                )
        except httpx.HTTPStatusError as exc:
            _logger.warning(f"NVD request failed ({exc.response.status_code}) — corpus fallback")
            return self._fallback_to_kb(cve_id)
        except httpx.RequestError as exc:
            _logger.warning(f"NVD request error ({exc}) — corpus fallback")
            return self._fallback_to_kb(cve_id)

    def check_package_advisory(self, package: str) -> "CVEAdvisory | EscalationResult":
        if not self._check_rate_limit("osv"):
            _logger.warning(f"OSV rate limit exhausted — falling back to corpus for {package}")
            return self._fallback_to_kb(package)

        endpoint = self._config.mcp_servers.osv
        url = f"{endpoint}/v1/query"
        try:
            with httpx.Client() as client:
                response = client.post(
                    url,
                    json={"package": {"name": package}},
                    headers=self._headers(),
                )
                response.raise_for_status()
                data = response.json()
                vulns = data.get("vulns", [])
                description = vulns[0].get("summary", "") if vulns else ""
                cve_id = vulns[0].get("id", package) if vulns else package
                return CVEAdvisory(
                    id=cve_id, description=description, severity="unknown", source="osv"
                )
        except httpx.HTTPStatusError as exc:
            _logger.warning(f"OSV request failed ({exc.response.status_code}) — corpus fallback")
            return self._fallback_to_kb(package)
        except httpx.RequestError as exc:
            _logger.warning(f"OSV request error ({exc}) — corpus fallback")
            return self._fallback_to_kb(package)

    # ── v2 methods ────────────────────────────────────────────────────────────

    def ghsa_lookup(
        self, package: str, version: str, ecosystem: str
    ) -> list[CVEAdvisory]:
        """Query GitHub Security Advisories for a package/version."""
        url = "https://api.github.com/advisories"
        try:
            response = httpx.get(
                url,
                params={"ecosystem": ecosystem, "package": package, "version": version},
                headers=self._headers(),
                timeout=10.0,
            )
            response.raise_for_status()
            items = response.json() if isinstance(response.json(), list) else []
            return [
                CVEAdvisory(
                    id=item.get("ghsa_id", "unknown"),
                    description=item.get("summary", ""),
                    severity=item.get("severity", "unknown"),
                    source="ghsa",
                )
                for item in items
            ]
        except (httpx.HTTPStatusError, httpx.RequestError) as exc:
            _logger.warning(f"GHSA lookup failed for {package}: {exc}")
            return []

    def snyk_lookup(
        self, package: str, version: str, ecosystem: str
    ) -> list[CVEAdvisory]:
        """Query Snyk for package vulnerabilities; falls back to cve_snapshot corpus."""
        if not self._check_rate_limit("snyk"):
            _logger.warning(f"Snyk rate limit exhausted — falling back to corpus for {package}")
            entries = self._kb.query(package, category="security", language="")
            return [
                CVEAdvisory(
                    id=getattr(e, "id", package),
                    description=getattr(e, "content", ""),
                    severity="unknown",
                    source="fallback_corpus",
                )
                for e in entries
            ]

        snyk_url = "https://api.snyk.io/rest/orgs/public/packages"
        try:
            response = httpx.get(
                f"{snyk_url}/{ecosystem}/{package}/{version}/issues",
                headers=self._headers(),
                timeout=10.0,
            )
            response.raise_for_status()
            vulns = response.json().get("data", [])
            return [
                CVEAdvisory(
                    id=v.get("id", "unknown"),
                    description=v.get("attributes", {}).get("title", ""),
                    severity=v.get("attributes", {}).get("severity", "unknown"),
                    source="snyk",
                )
                for v in vulns
            ]
        except (httpx.HTTPStatusError, httpx.RequestError) as exc:
            _logger.warning(f"Snyk lookup failed for {package}: {exc}")
            return []

    def owasp_check(self, code_snippet: str, language: str) -> list[OWASPMatch]:  # noqa: ARG002
        """Pattern-match code snippet against OWASP Top 10 vulnerability patterns."""
        matches: list[OWASPMatch] = []

        # A03:2021 — Injection: SQL string concatenation
        import re as _re
        sql_keywords = r"(?:SELECT|INSERT|UPDATE|DELETE|DROP|ALTER|CREATE)\s"
        concat_patterns = [
            _re.compile(r'["\'].*' + sql_keywords + r'.*["\'].*\+', _re.IGNORECASE),
            _re.compile(r'\+.*["\'].*' + sql_keywords, _re.IGNORECASE),
            _re.compile(r'f["\'].*\{.*\}.*' + sql_keywords, _re.IGNORECASE),
        ]
        safe_patterns = [
            _re.compile(r'execute\s*\(.*%s', _re.IGNORECASE),
            _re.compile(r'execute\s*\(.*\?', _re.IGNORECASE),
            _re.compile(r'execute\s*\(.*:\w+', _re.IGNORECASE),
        ]

        is_safe = any(p.search(code_snippet) for p in safe_patterns)
        if not is_safe:
            is_injection = any(p.search(code_snippet) for p in concat_patterns)
            if is_injection:
                matches.append(OWASPMatch(
                    category="A03:2021",
                    description="Potential SQL injection via string concatenation",
                    confidence="high",
                ))

        return matches
