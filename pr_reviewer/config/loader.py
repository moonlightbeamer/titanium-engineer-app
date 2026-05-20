"""ConfigLoader — fetches and parses per-repo .github/pr-auto-review.yml."""

from typing import TYPE_CHECKING, Any

import yaml
from pydantic import ValidationError

from pr_reviewer.config.schema import Config
from pr_reviewer.logging import get_logger

if TYPE_CHECKING:
    from pr_reviewer.store.github_client import GitHubAPIClient

_logger = get_logger(__name__)

_CONFIG_PATH = ".github/pr-auto-review.yml"


class ConfigLoader:
    def __init__(self, github_client: "GitHubAPIClient") -> None:
        self._client = github_client

    def load(self, repo_id: str, installation_id: int) -> Config:
        try:
            raw = self._client.get_file_content(repo=repo_id, path=_CONFIG_PATH)
        except Exception:
            return Config()

        parsed: Any
        try:
            parsed = yaml.safe_load(raw)
        except yaml.YAMLError:
            _logger.warning("invalid Config YAML for repo; using defaults")
            return Config()

        if not isinstance(parsed, dict):
            kind = type(parsed).__name__
            _logger.warning(f"invalid Config: expected mapping, got {kind}; using defaults")
            return Config()

        try:
            return Config.model_validate(parsed)
        except ValidationError:
            _logger.warning("invalid Config: schema validation failed; using defaults")
            return Config()
