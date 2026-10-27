#!/usr/bin/env bash
# SessionStart (Claude Code) / sessionStart (Cursor) hook: print one PostgreSQL-standards context
# line when the workspace uses PostgreSQL. Always exits 0 so the assistant reads stdout and is
# never blocked.
#
# Claude Code runs the hook in the project directory and adds plain stdout to the context.
# Cursor runs a plugin hook from the plugin's install directory and reads additional_context
# from JSON (https://cursor.com/docs/agent/hooks), so there the hook moves to CURSOR_PROJECT_DIR
# and prints JSON.
set -u

# CURSOR_PLUGIN_ROOT is set only for a Cursor plugin hook, so Claude Code started from a Cursor
# terminal still takes the Claude Code path.
cursor=""
if [ -n "${CURSOR_PLUGIN_ROOT:-}" ]; then
  cursor=1
  cd "${CURSOR_PROJECT_DIR:-.}" 2>/dev/null || exit 0
fi

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
  # Fixed literals with no quotes or backslashes, so the JSON form needs no escaping.
  skills="pgsql-query · pgsql-jsonb · pgsql-schema · pgsql-indexing · pgsql-performance · pgsql-migrations"
  if [ -n "$cursor" ]; then
    line="› PostgreSQL workspace: pgsql-coding (PostgreSQL 18 floor, 19 as hints). Open /pgsql-coding, then the skill for the change (/pgsql-query · /pgsql-jsonb · /pgsql-schema · /pgsql-indexing · /pgsql-performance · /pgsql-migrations); pgsql-reviewer for a review, pgsql-plan-analyst for a long EXPLAIN plan${lint}. EXPLAIN (ANALYZE, BUFFERS) before proposing an index or rewrite; squawk on migrations."
  else
    line="› PostgreSQL workspace: pgsql-coding (PostgreSQL 18 floor, 19 as hints). Load pgsql-coding then the skill for the change (${skills}); pgsql-reviewer for a review, pgsql-plan-analyst for a long EXPLAIN plan${lint}. EXPLAIN (ANALYZE, BUFFERS) before proposing an index or rewrite; squawk on migrations."
  fi
  if [ -n "$cursor" ]; then
    printf '{"additional_context":"%s"}\n' "$line"
  else
    echo "$line"
  fi
fi

exit 0
