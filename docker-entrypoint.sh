#!/bin/sh
set -e

case "$1" in
  api)
    echo "Running database migrations..."
    alembic upgrade head
    echo "Starting API server..."
    exec uvicorn pr_reviewer.api.main:app --host 0.0.0.0 --port 8000
    ;;
  worker-review)
    exec celery -A pr_reviewer.workers worker -Q review_jobs --pool=solo --loglevel info
    ;;
  worker-feedback)
    exec celery -A pr_reviewer.workers worker -Q feedback_jobs --pool=solo --loglevel info
    ;;
  worker-indexer)
    exec celery -A pr_reviewer.workers worker -Q indexer_jobs --pool=solo --loglevel info
    ;;
  beat)
    exec celery -A pr_reviewer.workers beat --loglevel info
    ;;
  seed-kb)
    echo "Bootstrapping KB entries (CVE snapshot + all corpora) into PostgreSQL..."
    python -m pr_reviewer.kb.cli bootstrap
    echo "Syncing KB to ChromaDB with Azure embeddings..."
    python -m pr_reviewer.kb.cli sync
    echo "KB seeding complete."
    ;;
  migrate)
    exec alembic upgrade head
    ;;
  *)
    exec "$@"
    ;;
esac
