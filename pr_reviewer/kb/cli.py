"""Knowledge Base CLI — manage KB entries via the 'kb' command group."""

from __future__ import annotations

import json
import os
import re
import uuid
from datetime import UTC, datetime
from typing import Any

import click
import sqlalchemy as sa
from dotenv import load_dotenv
from sqlalchemy import MetaData, Table, Column, text

load_dotenv()

from pr_reviewer.logging import get_logger

_logger = get_logger(__name__)

# ── Schema helpers ─────────────────────────────────────────────────────────────

_metadata = MetaData()

_kb_entries = Table(
    "knowledge_base_entries",
    _metadata,
    Column("id", sa.Text, primary_key=True),
    Column("corpus", sa.Text, nullable=False),
    Column("category", sa.Text, nullable=False),
    Column("content", sa.Text, nullable=False),
    Column("problem_description", sa.Text, nullable=False),
    Column("resolution", sa.Text, nullable=False),
    Column("code_pattern", sa.Text, nullable=True),
    Column("language", sa.Text, nullable=True),
    Column("model_version", sa.Text, nullable=False, default="text-embedding-3-small"),
    Column("is_draft", sa.Boolean, nullable=False, default=False),
    Column("is_active", sa.Boolean, nullable=False, default=True),
    Column("version", sa.Integer, nullable=False, default=1),
    Column("created_at", sa.DateTime, nullable=False),
)


def _create_tables(engine: Any) -> None:
    """Create KB tables; safe to call on existing DBs (checkfirst=True)."""
    _metadata.create_all(engine, checkfirst=True)


# ── Validation ────────────────────────────────────────────────────────────────

_REQUIRED_FIELDS = ("corpus", "category", "content", "problem_description", "resolution")
_MIN_DESC_LEN = 50
_MAX_CODE_LINES = 3
_CODE_LINE_RE = re.compile(
    r"^\s*[{};()=>]|def |class |import |function ",
    re.MULTILINE,
)


def _validate_entry(data: dict) -> str | None:
    """Return error message or None if valid."""
    for field in _REQUIRED_FIELDS:
        if field not in data or not data[field]:
            return f"Missing required field: '{field}'"

    for field in ("problem_description", "resolution"):
        if len(data[field]) < _MIN_DESC_LEN:
            return f"'{field}' must be at least {_MIN_DESC_LEN} characters (minimum 50 characters)"

    code_pattern = data.get("code_pattern")
    if code_pattern:
        matches = _CODE_LINE_RE.findall(code_pattern)
        if len(matches) > _MAX_CODE_LINES:
            return (
                "abstract description required in 'code_pattern': "
                f"detected {len(matches)} code-like lines (max {_MAX_CODE_LINES})"
            )

    return None


# ── CLI group ─────────────────────────────────────────────────────────────────


@click.group()
@click.option("--db-url", envvar="DATABASE_URL", default=None, help="SQLAlchemy DB URL")
@click.pass_context
def kb(ctx: click.Context, db_url: str | None) -> None:
    """Manage the PR-reviewer knowledge base."""
    ctx.ensure_object(dict)
    if "engine" not in ctx.obj:
        if not db_url:
            raise click.UsageError("--db-url is required (or set DATABASE_URL env var)")
        ctx.obj["engine"] = sa.create_engine(db_url)
        _create_tables(ctx.obj["engine"])


# ── add ───────────────────────────────────────────────────────────────────────


@kb.command("add")
@click.option("--draft", is_flag=True, default=False, help="Add as draft (requires approval)")
@click.pass_obj
def cmd_add(obj: dict, draft: bool) -> None:
    """Add a new knowledge base entry (reads JSON from stdin)."""
    raw = click.get_text_stream("stdin").read()
    try:
        data = json.loads(raw)
    except json.JSONDecodeError as exc:
        raise click.ClickException(f"Invalid JSON: {exc}") from exc

    error = _validate_entry(data)
    if error:
        raise click.ClickException(error)

    engine = obj["engine"]
    entry_id = str(uuid.uuid4())
    now = datetime.now(UTC).isoformat()

    with engine.connect() as conn:
        conn.execute(
            text(
                "INSERT INTO knowledge_base_entries "
                "(id,corpus,category,content,problem_description,resolution,"
                "code_pattern,language,model_version,is_draft,is_active,version,created_at) "
                "VALUES (:id,:corpus,:category,:content,:problem_description,:resolution,"
                ":code_pattern,:language,:model_version,:is_draft,:is_active,:version,:created_at)"
            ),
            {
                "id": entry_id,
                "corpus": data["corpus"],
                "category": data["category"],
                "content": data["content"],
                "problem_description": data["problem_description"],
                "resolution": data["resolution"],
                "code_pattern": data.get("code_pattern"),
                "language": data.get("language"),
                "model_version": data.get("model_version", "text-embedding-3-small"),
                "is_draft": draft,
                "is_active": True,
                "version": data.get("version", 1),
                "created_at": now,
            },
        )
        conn.commit()
    click.echo(f"Added entry {entry_id}" + (" (draft)" if draft else ""))


# ── approve ───────────────────────────────────────────────────────────────────


@kb.command("approve")
@click.argument("entry_id")
@click.pass_obj
def cmd_approve(obj: dict, entry_id: str) -> None:
    """Approve a draft entry (sets is_draft=False)."""
    engine = obj["engine"]
    with engine.connect() as conn:
        result = conn.execute(
            text("UPDATE knowledge_base_entries SET is_draft=:val WHERE id=:id"),
            {"val": False, "id": entry_id},
        )
        conn.commit()
    if result.rowcount == 0:
        raise click.ClickException(f"Entry {entry_id} not found")
    click.echo(f"Approved {entry_id}")


# ── deprecate ─────────────────────────────────────────────────────────────────


@kb.command("deprecate")
@click.argument("entry_id")
@click.pass_obj
def cmd_deprecate(obj: dict, entry_id: str) -> None:
    """Deprecate an entry (sets is_active=False; row is retained)."""
    engine = obj["engine"]
    with engine.connect() as conn:
        result = conn.execute(
            text("UPDATE knowledge_base_entries SET is_active=:val WHERE id=:id"),
            {"val": False, "id": entry_id},
        )
        conn.commit()
    if result.rowcount == 0:
        raise click.ClickException(f"Entry {entry_id} not found")
    click.echo(f"Deprecated {entry_id}")


# ── list ──────────────────────────────────────────────────────────────────────


@kb.command("list")
@click.option("--corpus", default=None, help="Filter by corpus")
@click.option("--include-drafts", is_flag=True, default=False)
@click.pass_obj
def cmd_list(obj: dict, corpus: str | None, include_drafts: bool) -> None:
    """List active (non-deprecated) knowledge base entries."""
    engine = obj["engine"]
    conditions = ["is_active=1"]
    params: dict = {}
    if not include_drafts:
        conditions.append("is_draft=0")
    if corpus:
        conditions.append("corpus=:corpus")
        params["corpus"] = corpus
    where = " AND ".join(conditions)

    with engine.connect() as conn:
        rows = conn.execute(
            text(f"SELECT id, corpus, category, content, version, is_draft FROM knowledge_base_entries WHERE {where}"),
            params,
        ).fetchall()

    if not rows:
        click.echo("No entries found.")
        return
    for row in rows:
        draft_label = " [DRAFT]" if row[5] else ""
        click.echo(f"{row[0]}  corpus={row[1]}  cat={row[2]}  v{row[4]}{draft_label}  {row[3][:60]}")


# ── show ──────────────────────────────────────────────────────────────────────


@kb.command("show")
@click.argument("entry_id")
@click.pass_obj
def cmd_show(obj: dict, entry_id: str) -> None:
    """Show full details of a single entry."""
    engine = obj["engine"]
    with engine.connect() as conn:
        row = conn.execute(
            text("SELECT * FROM knowledge_base_entries WHERE id=:id"),
            {"id": entry_id},
        ).fetchone()
    if not row:
        raise click.ClickException(f"Entry {entry_id} not found")
    click.echo(json.dumps(dict(row._mapping), default=str, indent=2))


# ── rollback ──────────────────────────────────────────────────────────────────


@kb.command("rollback")
@click.option("--corpus", required=True, help="Corpus to roll back")
@click.option("--version", "target_version", required=True, type=int, help="Version to activate")
@click.pass_obj
def cmd_rollback(obj: dict, corpus: str, target_version: int) -> None:
    """Roll back a corpus to a specific version."""
    engine = obj["engine"]
    with engine.connect() as conn:
        # Deactivate all versions of this corpus
        conn.execute(
            text("UPDATE knowledge_base_entries SET is_active=0 WHERE corpus=:corpus"),
            {"corpus": corpus},
        )
        # Activate target version
        conn.execute(
            text(
                "UPDATE knowledge_base_entries SET is_active=1 "
                "WHERE corpus=:corpus AND version=:version"
            ),
            {"corpus": corpus, "version": target_version},
        )
        conn.commit()
    click.echo(f"Rolled back corpus '{corpus}' to version {target_version}")


# ── reembed ───────────────────────────────────────────────────────────────────


@kb.command("reembed")
@click.option("--corpus", required=True, help="Corpus to reembed ('all' for every corpus)")
@click.option("--model-version", required=True, help="New embedding model version")
@click.pass_obj
def cmd_reembed(obj: dict, corpus: str, model_version: str) -> None:
    """Update model_version on all active entries (re-embedding deferred to pipeline)."""
    engine = obj["engine"]
    with engine.connect() as conn:
        if corpus == "all":
            result = conn.execute(
                text(
                    "UPDATE knowledge_base_entries SET model_version=:mv "
                    "WHERE is_active=1"
                ),
                {"mv": model_version},
            )
        else:
            result = conn.execute(
                text(
                    "UPDATE knowledge_base_entries SET model_version=:mv "
                    "WHERE corpus=:corpus AND is_active=1"
                ),
                {"mv": model_version, "corpus": corpus},
            )
        conn.commit()
    click.echo(f"Updated model_version to '{model_version}' on {result.rowcount} entries")


# ── validate ──────────────────────────────────────────────────────────────────


@kb.command("validate")
@click.pass_obj
def cmd_validate(obj: dict) -> None:
    """Validate all active entries for required fields and quality."""
    engine = obj["engine"]
    with engine.connect() as conn:
        rows = conn.execute(
            text("SELECT id, problem_description, resolution FROM knowledge_base_entries WHERE is_active=1")
        ).fetchall()

    issues = 0
    for row in rows:
        entry_id, prob, res = row
        if len(prob) < _MIN_DESC_LEN:
            click.echo(f"WARN {entry_id}: problem_description too short")
            issues += 1
        if not res:
            click.echo(f"WARN {entry_id}: resolution is empty")
            issues += 1
    click.echo(f"Validated {len(rows)} entries; {issues} issue(s) found")


# ── bootstrap ─────────────────────────────────────────────────────────────────

_BOOTSTRAP_CVE_ENTRIES = [
    {
        "corpus": "cve_snapshot",
        "category": "security",
        "content": "SQL injection via unsanitized input in query parameters.",
        "problem_description": "User-controlled input concatenated directly into SQL query without parameterization.",
        "resolution": "Use parameterized queries or prepared statements for all SQL operations.",
        "language": None,
    },
    {
        "corpus": "cve_snapshot",
        "category": "security",
        "content": "Cross-site scripting (XSS) via unsanitized HTML output.",
        "problem_description": "User-supplied content rendered as raw HTML without escaping, enabling script injection.",
        "resolution": "Escape all user-supplied content before rendering in HTML context using context-aware encoding.",
        "language": None,
    },
    {
        "corpus": "cve_snapshot",
        "category": "security",
        "content": "Insecure direct object reference allowing unauthorized resource access.",
        "problem_description": "API endpoint exposes internal object identifiers without authorization checks on each request.",
        "resolution": "Validate authorization for every resource access; never rely on obscurity of identifiers.",
        "language": None,
    },
    {
        "corpus": "cve_snapshot",
        "category": "security",
        "content": "Hardcoded credentials in source code or configuration files.",
        "problem_description": "Secrets such as API keys or passwords embedded directly in the codebase and committed to VCS.",
        "resolution": "Store secrets in environment variables or a secret manager; rotate any exposed credentials immediately.",
        "language": None,
    },
    {
        "corpus": "cve_snapshot",
        "category": "security",
        "content": "Prototype pollution via unvalidated deep object merge.",
        "problem_description": "Deep merge or extend operations performed on user-supplied objects can poison the Object prototype.",
        "resolution": "Use safe merge libraries; validate and sanitize keys; avoid recursive merge on untrusted input.",
        "language": "javascript",
    },
]

_BOOTSTRAP_GUIDELINE_ENTRIES = [
    {
        "corpus": "org_guidelines",
        "category": "style",
        "content": "All public APIs must have type annotations and docstrings.",
        "problem_description": "Lack of type annotations reduces IDE support and increases the likelihood of type-related bugs in production.",
        "resolution": "Add PEP-484 type hints to all function signatures and concise docstrings to all public methods.",
        "language": "python",
    },
]


@kb.command("bootstrap")
@click.pass_obj
def cmd_bootstrap(obj: dict) -> None:
    """Seed the DB with minimum CVE and org-guidelines entries."""
    engine = obj["engine"]
    now = datetime.now(UTC).isoformat()
    inserted = 0

    all_seeds = _BOOTSTRAP_CVE_ENTRIES + _BOOTSTRAP_GUIDELINE_ENTRIES
    # Track next version per corpus so each entry gets a unique version number
    corpus_versions: dict[str, int] = {}
    with engine.connect() as conn:
        # Start each corpus version counter above any existing entries
        for seed in all_seeds:
            corpus = seed["corpus"]
            if corpus not in corpus_versions:
                row = conn.execute(
                    text("SELECT COALESCE(MAX(version), 0) FROM knowledge_base_entries WHERE corpus=:corpus"),
                    {"corpus": corpus},
                ).scalar()
                corpus_versions[corpus] = (row or 0) + 1
        for seed in all_seeds:
            corpus = seed["corpus"]
            already = conn.execute(
                text(
                    "SELECT 1 FROM knowledge_base_entries "
                    "WHERE corpus=:corpus AND content=:content LIMIT 1"
                ),
                {"corpus": corpus, "content": seed["content"]},
            ).scalar()
            if already:
                continue
            version = corpus_versions[corpus]
            corpus_versions[corpus] += 1
            conn.execute(
                text(
                    "INSERT INTO knowledge_base_entries "
                    "(id,corpus,category,content,problem_description,resolution,"
                    "code_pattern,language,model_version,is_draft,is_active,version,created_at) "
                    "VALUES (:id,:corpus,:category,:content,:problem_description,:resolution,"
                    ":code_pattern,:language,:model_version,:is_draft,:is_active,:version,:created_at)"
                ),
                {
                    "id": str(uuid.uuid4()),
                    "corpus": corpus,
                    "category": seed["category"],
                    "content": seed["content"],
                    "problem_description": seed["problem_description"],
                    "resolution": seed["resolution"],
                    "code_pattern": None,
                    "language": seed.get("language"),
                    "model_version": os.getenv("AZURE_OPENAI_EMBEDDING_DEPLOYMENT", "text-embedding-3-large"),
                    "is_draft": False,
                    "is_active": True,
                    "version": version,
                    "created_at": now,
                },
            )
            inserted += 1
        conn.commit()
    skipped = len(all_seeds) - inserted
    click.echo(f"Bootstrapped {inserted} entries ({skipped} already present, skipped)")


@kb.command("sync")
@click.option(
    "--chroma-url",
    envvar="CHROMADB_URL",
    default="http://localhost:8001",
    help="ChromaDB HTTP URL",
)
@click.option(
    "--embedding-deployment",
    envvar="AZURE_OPENAI_EMBEDDING_DEPLOYMENT",
    required=True,
    help="Azure OpenAI embedding deployment name (AZURE_OPENAI_EMBEDDING_DEPLOYMENT)",
)
@click.pass_obj
def cmd_sync(obj: dict, chroma_url: str, embedding_deployment: str) -> None:
    """Push active PostgreSQL KB entries into ChromaDB using Azure OpenAI embeddings."""
    import os
    import urllib.parse

    import chromadb
    import openai

    engine = obj["engine"]
    with engine.connect() as conn:
        rows = conn.execute(
            text(
                "SELECT id, corpus, category, content, language, model_version "
                "FROM knowledge_base_entries WHERE is_active=true AND is_draft=false"
            )
        ).fetchall()

    if not rows:
        click.echo("No active entries found in PostgreSQL; nothing to sync.")
        return

    oai = openai.AzureOpenAI(
        api_key=os.environ["AZURE_OPENAI_API_KEY"],
        azure_endpoint=os.environ["AZURE_OPENAI_ENDPOINT"],
        api_version=os.getenv("AZURE_OPENAI_API_VERSION", "2024-08-01-preview"),
    )

    parsed = urllib.parse.urlparse(chroma_url)
    client = chromadb.HttpClient(host=parsed.hostname, port=parsed.port or 8001)

    synced = 0
    collections: dict[str, Any] = {}
    for row in rows:
        entry_id, corpus, category, content, language, model_version = row
        if corpus not in collections:
            # Create collection without a default embedding function — we supply vectors
            collections[corpus] = client.get_or_create_collection(
                corpus, embedding_function=None
            )
        col = collections[corpus]

        response = oai.embeddings.create(input=content, model=embedding_deployment)
        vector = response.data[0].embedding

        meta: dict[str, Any] = {
            "category": category or "",
            "model_version": model_version or embedding_deployment,
        }
        if language:
            meta["language"] = language

        col.upsert(
            ids=[str(entry_id)],
            embeddings=[vector],
            documents=[content],
            metadatas=[meta],
        )
        synced += 1
        click.echo(f"  embedded {corpus}/{str(entry_id)[:8]}…")

    click.echo(f"Synced {synced} entries to ChromaDB across {len(collections)} collection(s).")


if __name__ == "__main__":
    kb()
