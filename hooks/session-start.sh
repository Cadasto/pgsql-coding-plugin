#!/usr/bin/env bash
# SessionStart hook (host-agnostic): print one PostgreSQL-standards context line when the
# workspace uses PostgreSQL. Always exits 0 so the assistant reads stdout and is never blocked.
set -u

# Signals, cheapest first: a pgx or lib/pq import in go.mod, a PostgreSQL PDO extension in
# composer.json, a postgres image in a compose file, then any *.sql file (bounded search).
uses_postgres() {
  [ -f go.mod ] && grep -qE 'github\.com/(jackc/pgx|lib/pq)' go.mod && return 0
  [ -f composer.json ] && grep -qE '"ext-(pdo_)?pgsql"' composer.json && return 0
  for c in compose.yaml compose.yml docker-compose.yaml docker-compose.yml; do
    [ -f "$c" ] && grep -qiE 'image:[[:space:]]*["'\'']?[^[:space:]]*(postgres|postgis|timescaledb)' "$c" && return 0
  done
  find . -maxdepth 4 -name '*.sql' -not -path './vendor/*' -not -path './node_modules/*' \
    -not -path './.git/*' 2>/dev/null | grep -q . && return 0
  return 1
}

if uses_postgres; then
  lint=" · /pgsql-lint-setup adds squawk (no .squawk.toml found)"
  [ -e .squawk.toml ] && lint=""
  echo "› PostgreSQL workspace: pgsql-coding (PostgreSQL 18 floor, 19 as hints). Load pgsql-coding then the skill for the change (pgsql-query · pgsql-jsonb · pgsql-schema · pgsql-indexing · pgsql-performance · pgsql-migrations); pgsql-reviewer for a review, pgsql-plan-analyst for a long EXPLAIN plan${lint}. EXPLAIN (ANALYZE, BUFFERS) before proposing an index or rewrite; squawk on migrations."
fi

exit 0
