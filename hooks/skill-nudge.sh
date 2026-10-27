#!/usr/bin/env bash
# PostToolUse (Claude Code) / postToolUse on Write or StrReplace (Cursor) hook: after a .sql, .go
# or .php file is edited, name ONE focused pgsql-coding skill the edit calls for, as context the
# model reads: hookSpecificOutput.additionalContext (Claude Code) or additional_context (Cursor).
# Once per skill per session. Always exits 0; never blocks an edit.
#
# Go and PHP files only nudge on unmistakable SQL (a jsonb operator, DDL, a pgx or PDO call), so
# ordinary host-language edits stay silent; go-coding and php-coding own those.
set -u
f="${CLAUDE_FILE_PATH:-}"; sid=""; payload=""
if [ ! -t 0 ]; then
  payload="$(cat)"
  # Claude's tool_input.file_path; Cursor's StrReplace sends path and its Write fields are
  # undocumented, so accept both.
  [ -n "$f" ] || f="$(printf '%s' "$payload" | grep -oE '"(file_?[Pp]ath|path)"[[:space:]]*:[[:space:]]*"[^"]+"' | head -n1 | sed -E 's/.*"([^"]+)"$/\1/')"
  # Claude Code names the session session_id; Cursor names it conversation_id.
  sid="$(printf '%s' "$payload" | grep -oE '"(session|conversation)_id"[[:space:]]*:[[:space:]]*"[^"]+"' | head -n1 | sed -E 's/.*"([^"]+)"$/\1/')"
fi
[ -n "$f" ] || exit 0
# Cursor plugin hooks run in the plugin install. A relative tool path is relative to the
# workspace, which CURSOR_PROJECT_DIR names. Absolute paths are left as they are.
cursor=0
if [ -n "${CURSOR_PLUGIN_ROOT:-}" ] || printf '%s' "$payload" | grep -q '"cursor_version"'; then
  cursor=1
fi
if [ "$cursor" -eq 1 ] && [ -n "${CURSOR_PROJECT_DIR:-}" ]; then
  case "$f" in
    /*) ;;
    *) f="${CURSOR_PROJECT_DIR%/}/$f" ;;
  esac
fi
case "$f" in *.sql) kind=sql;; *.go) kind=go;; *.php) kind=php;; *) exit 0;; esac
[ -f "$f" ] || exit 0
[ -n "$sid" ] || sid="ppid$PPID"

# Pull one JSON string field out of the payload. The body pattern `(\\.|[^"\\])*` matches an
# escaped character or an ordinary one, so an embedded \" does not end the match early.
json_field() { printf '%s' "$payload" | grep -oE "\"$1\"[[:space:]]*:[[:space:]]*\"(\\\\.|[^\"\\\\])*\""; }

# Match the text the edit ADDS, not old_string or the tool_response echo: Claude Code's Edit
# new_string or Write content, and Cursor's StrReplace new_string. A payload with neither
# (Cursor Write, whose input fields are undocumented, or a manual run with a path only)
# matches the whole file.
case "$payload" in
  *'"new_string"'*|*'"content"'*) subject="$(json_field new_string; json_field content)"; what="this edit";;
  *)                              subject="$(cat "$f")"; what="this file";;
esac
# The added text is still JSON-escaped: a line break is \n, a tab \t. Turn those into spaces so
# a keyword at the start of a later line keeps its word edge.
subject="$(printf '%s' "$subject" | sed -e 's/\\[nrt]/ /g')"
# -e: some patterns start with "-", which grep would otherwise read as an option. No \b: BSD
# grep lacks it, so word edges are spelled out.
has() { printf '%s' "$subject" | grep -qiE -e "$1"; }

skill=""; topic=""
# A migration file routes to pgsql-migrations whatever it contains.
case "$f" in
  */migrations/*.sql|*/migration/*.sql|*/migrate/*.sql|*/db/migrate/*.sql) skill="pgsql-migrations"; topic="a migration file";;
esac
if [ -z "$skill" ] && has 'ALTER[[:space:]]+TABLE|DROP[[:space:]]+(TABLE|COLUMN|INDEX)|RENAME[[:space:]]+(COLUMN|TO)|CONCURRENTLY|lock_timeout'; then
  skill="pgsql-migrations"; topic="DDL on an existing table"
fi
if [ -z "$skill" ] && has 'jsonb|::json([^b]|$)|->>|#>>?|@>|<@|@\?|@@|JSON_(TABLE|VALUE|QUERY|EXISTS|OBJECT|ARRAY|OBJECTAGG|ARRAYAGG)|IS[[:space:]]+JSON|jsonpath'; then
  skill="pgsql-jsonb"; topic="JSON or jsonb"
fi
if [ -z "$skill" ] && has 'CREATE[[:space:]]+(UNIQUE[[:space:]]+)?INDEX|REINDEX|USING[[:space:]]+(gin|gist|brin|spgist|hash)|_pattern_ops|_trgm_ops|indisvalid|pg_stat_(user|all)_indexes|hypopg_'; then
  skill="pgsql-indexing"; topic="an index"
fi
if [ -z "$skill" ] && has 'EXPLAIN[[:space:]]*\(|EXPLAIN[[:space:]]+ANALYZE|pg_stat_(statements|activity)|pg_blocking_pids|auto_explain|CREATE[[:space:]]+STATISTICS|plan_cache_mode'; then
  skill="pgsql-performance"; topic="a query plan or statistics"
fi
if [ -z "$skill" ] && has 'CREATE[[:space:]]+(TABLE|TYPE|DOMAIN|FUNCTION|PROCEDURE|TRIGGER|POLICY|VIEW)|CREATE[[:space:]]+OR[[:space:]]+REPLACE|GRANT[[:space:]]|GENERATED[[:space:]]+(ALWAYS|BY[[:space:]]+DEFAULT)|SECURITY[[:space:]]+DEFINER|ROW[[:space:]]+LEVEL[[:space:]]+SECURITY|PARTITION[[:space:]]+BY'; then
  skill="pgsql-schema"; topic="a table, function, trigger or policy"
fi
if [ -z "$skill" ]; then
  case "$kind" in
    sql) has '(^|[^a-z_])(SELECT|INSERT|UPDATE|DELETE|MERGE|WITH)([^a-z_]|$)' && { skill="pgsql-query"; topic="a SQL statement"; } ;;
    go)  has 'pgx\.|pgxpool\.|pgconn\.|\.QueryRow\(|\.Query\(ctx|\.Exec\(ctx|SendBatch\(|CopyFrom\(' && { skill="pgsql-query"; topic="a pgx query"; } ;;
    php) has '->prepare\(|->query\(|PDO::|Pdo\\+Pgsql' && { skill="pgsql-query"; topic="a PDO query"; } ;;
  esac
fi
[ -n "$skill" ] || exit 0
marker="${TMPDIR:-/tmp}/pgsql-coding-nudge.${sid}.${skill}"
[ -e "$marker" ] && exit 0
# what/topic/skill are fixed literals set in this script (no quotes or backslashes). The Cursor
# plugin path comes from outside, so it is JSON-escaped before it joins the message.
if [ "$cursor" -eq 1 ]; then
  # Cursor has no Skill tool; name the skill's file in the plugin install, which holds hooks/.
  root="${CURSOR_PLUGIN_ROOT:-$(cd "$(dirname "$0")/.." && pwd)}"
  root="$(printf '%s' "${root%/}" | sed -e 's/\\/\\\\/g' -e 's/"/\\"/g')"
  how="read the ${skill} skill, ${root}/skills/${skill}/SKILL.md,"
else
  how="load pgsql-coding:${skill}"
fi
msg="› pgsql-coding: ${what} touches ${topic}; ${how} before continuing."
# Cursor first: it sends hook_event_name too, and every Cursor payload carries cursor_version.
if [ "$cursor" -eq 1 ]; then
  # Cursor postToolUse: additional_context is injected after the tool result
  # (https://cursor.com/docs/agent/hooks).
  out="$(printf '{"additional_context":"%s"}' "$msg")"
elif [ -n "${CLAUDE_PLUGIN_ROOT:-}" ] || printf '%s' "$payload" | grep -qE '"hook_event_name"[[:space:]]*:[[:space:]]*"PostToolUse"'; then
  # Claude Code: additionalContext reaches the model; a top-level systemMessage reaches only the
  # user (https://code.claude.com/docs/en/hooks).
  out="$(printf '{"hookSpecificOutput":{"hookEventName":"PostToolUse","additionalContext":"%s"}}' "$msg")"
else
  out="$msg"                                       # a manual run: plain line
fi
# Mark the skill as nudged only once the message is out, so a failed write does not use it up.
printf '%s\n' "$out" && { : > "$marker"; } 2>/dev/null
exit 0
