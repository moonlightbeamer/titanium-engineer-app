"""Config schema — Pydantic frozen model. Loader implemented in task 9."""

from pydantic import BaseModel, ConfigDict, Field


class MCPServersConfig(BaseModel):
    model_config = ConfigDict(frozen=True)

    nvd: str = "https://services.nvd.nist.gov"
    semgrep: str = "https://semgrep.dev"


class KnowledgeBaseConfig(BaseModel):
    model_config = ConfigDict(frozen=True)

    cve_snapshot: bool = True
    language_best_practices: bool = True
    language_corpus_weights: dict[str, float] = Field(default_factory=dict)


class Config(BaseModel):
    model_config = ConfigDict(frozen=True)

    tool_budget: int = 20
    min_severity: str = "low"
    auto_approve_on_no_findings: bool = False
    review_draft_prs: bool = False
    ignore_patterns_override: list[str] | None = None
    ignore_patterns_extend: list[str] | None = None
    max_linter_files: int = 5
    mcp_servers: MCPServersConfig = Field(default_factory=MCPServersConfig)
    knowledge_base: KnowledgeBaseConfig = Field(default_factory=KnowledgeBaseConfig)
