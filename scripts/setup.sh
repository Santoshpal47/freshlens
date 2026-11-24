#!/usr/bin/env bash
# One-time local setup: Python deps + a project-local JDK 17 (Spark 4 needs Java 17/21).
set -euo pipefail
cd "$(dirname "$0")/.."
uv sync --dev --extra dashboard
if ! ls .jdk/jdk-17* >/dev/null 2>&1 && [ -z "${JAVA_HOME:-}" ]; then
  uv run python -c "import jdk; print(jdk.install('17', path='.jdk'))"
fi
[ -f .env ] || cp .env.example .env
echo "Done. Put your data.gov.in key in .env, then: uv run freshlens backfill && uv run fpr daily"
