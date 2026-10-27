#!/usr/bin/env bash
# Bash tests for the plugin hooks. Run: ./scripts/hooks-test.sh  (exit 0 = all pass)
set -u
here="$(cd "$(dirname "$0")/.." && pwd)"; fails=0
ok()   { echo "ok   $1"; }
fail() { echo "FAIL $1"; fails=$((fails+1)); }
chk()        { case "$2" in *"$3"*) ok "$1";; *) fail "$1: got '$2'";; esac; }
chk_absent() { case "$2" in *"$3"*) fail "$1: unexpected '$3' in '$2'";; *) ok "$1";; esac; }
chk_silent() { if [ -z "$2" ]; then ok "$1"; else fail "$1: expected silence, got '$2'"; fi; }

t="$(mktemp -d)"; trap 'rm -rf "$t"' EXIT

# --- session-start -----------------------------------------------------------------------------
banner() { (cd "$1" && bash "$here/hooks/session-start.sh"); }
mkdir -p "$t/go-pgx" "$t/php-pdo" "$t/compose" "$t/sql-only/db" "$t/with-squawk" "$t/go-plain" "$t/none"
printf 'module x\n\ngo 1.26\n\nrequire github.com/jackc/pgx/v5 v5.7.0\n' > "$t/go-pgx/go.mod"
printf '{"require":{"ext-pdo_pgsql":"*"}}\n' > "$t/php-pdo/composer.json"
printf 'services:\n  db:\n    image: postgres:18\n' > "$t/compose/compose.yaml"
printf 'SELECT 1;\n' > "$t/sql-only/db/q.sql"
printf 'SELECT 1;\n' > "$t/with-squawk/q.sql"; : > "$t/with-squawk/.squawk.toml"
printf 'module x\n\ngo 1.26\n' > "$t/go-plain/go.mod"

chk "pgx in go.mod is detected"            "$(banner "$t/go-pgx")"   "PostgreSQL workspace"
chk "pdo_pgsql in composer.json is detected" "$(banner "$t/php-pdo")" "PostgreSQL workspace"
chk "postgres image in compose is detected" "$(banner "$t/compose")" "PostgreSQL workspace"
chk "a .sql file is detected"              "$(banner "$t/sql-only")" "PostgreSQL workspace"
chk "banner names the reviewer"            "$(banner "$t/sql-only")" "pgsql-reviewer"
chk "banner names the plan analyst"        "$(banner "$t/sql-only")" "pgsql-plan-analyst"
chk "banner states the version floor"      "$(banner "$t/sql-only")" "PostgreSQL 18 floor"
chk "no squawk config offers lint setup"   "$(banner "$t/sql-only")" "/pgsql-lint-setup"
chk_absent "squawk config omits lint setup" "$(banner "$t/with-squawk")" "/pgsql-lint-setup"
chk_silent "go repo without pgx is silent" "$(banner "$t/go-plain")"
chk_silent "unrelated repo is silent"      "$(banner "$t/none")"

# --- skill-nudge -------------------------------------------------------------------------------
# p_edit/p_write mirror a real Claude Code PostToolUse payload (hook_event_name, tool_input with
# BOTH old_string and new_string, a tool_response echo); p_path mirrors Cursor's afterFileEdit.
p_edit() { # SESSION FILE OLD NEW RESPONSE
  printf '{"session_id":"%s","hook_event_name":"PostToolUse","tool_name":"Edit","tool_input":{"file_path":"%s","old_string":"%s","new_string":"%s"},"tool_response":{"filePath":"%s","originalFile":"%s"}}' \
    "$1" "$2" "$3" "$4" "$2" "${5:-}"
}
p_write() { printf '{"session_id":"%s","hook_event_name":"PostToolUse","tool_name":"Write","tool_input":{"file_path":"%s","content":"%s"}}' "$1" "$2" "$3"; }
p_path()  { printf '{"session_id":"%s","file_path":"%s"}' "$1" "$2"; }
nudge() { # NAME PAYLOAD -> stdout; flags a non-zero exit
  local out st
  out="$(printf '%s' "$2" | bash "$here/hooks/skill-nudge.sh")"; st=$?
  [ "$st" -eq 0 ] || fail "$1: hook exited $st (a non-zero PostToolUse hook is a failed hook)"
  printf '%s' "$out"
}
clean() { rm -f "${TMPDIR:-/tmp}/pgsql-coding-nudge.$1".* 2>/dev/null; }

mkdir -p "$t/repo/db/migrations"
: > "$t/repo/db/migrations/0001_init.sql"; : > "$t/repo/q.sql"; : > "$t/repo/store.go"; : > "$t/repo/Repo.php"; : > "$t/repo/notes.md"
s="pg-test-$$"; clean "$s"
chk "migration path nudges pgsql-migrations"  "$(nudge a "$(p_edit "$s" "$t/repo/db/migrations/0001_init.sql" '' 'SELECT 1;')")" "pgsql-coding:pgsql-migrations"
chk "jsonb edit nudges pgsql-jsonb"           "$(nudge b "$(p_edit "$s" "$t/repo/q.sql" '' "SELECT doc->>'k' FROM t")")" "pgsql-coding:pgsql-jsonb"
chk "CREATE INDEX nudges pgsql-indexing"      "$(nudge c "$(p_edit "$s" "$t/repo/q.sql" '' 'CREATE INDEX ON t (a);')")" "pgsql-coding:pgsql-indexing"
chk "EXPLAIN nudges pgsql-performance"        "$(nudge d "$(p_edit "$s" "$t/repo/q.sql" '' 'EXPLAIN (ANALYZE, BUFFERS) SELECT 1;')")" "pgsql-coding:pgsql-performance"
chk "CREATE TABLE nudges pgsql-schema"        "$(nudge e "$(p_edit "$s" "$t/repo/q.sql" '' 'CREATE TABLE t (id bigint);')")" "pgsql-coding:pgsql-schema"
chk "a SELECT nudges pgsql-query"             "$(nudge f "$(p_edit "$s" "$t/repo/q.sql" '' 'select id from t where a = 1;')")" "pgsql-coding:pgsql-query"
chk_silent "second query edit is silent"      "$(nudge g "$(p_edit "$s" "$t/repo/q.sql" '' 'SELECT 2;')")"
clean "$s"

s2="pg-test-host-$$"; clean "$s2"
chk "pgx call in Go nudges pgsql-query"       "$(nudge h "$(p_edit "$s2" "$t/repo/store.go" '' 'rows, err := pool.Query(ctx, q, id)')")" "pgsql-coding:pgsql-query"
chk "PDO prepare in PHP nudges pgsql-query"   "$(nudge i "$(p_edit "$s2-php" "$t/repo/Repo.php" '' '$st = $pdo->prepare($sql);')")" "pgsql-coding:pgsql-query"
chk_silent "plain Go edit is silent"          "$(nudge j "$(p_edit "$s2-plain" "$t/repo/store.go" '' 'x := 1')")"
chk_silent "non-SQL file is silent"           "$(nudge k "$(p_edit "$s2-md" "$t/repo/notes.md" '' 'CREATE INDEX')")"
clean "$s2"; clean "$s2-php"; clean "$s2-plain"; clean "$s2-md"

# Classify from the text the edit ADDS. Each payload carries jsonb somewhere a naive grep would
# find it (the deleted text, the tool_response echo) while the added text is plain.
s3="pg-test-edit-$$"; clean "$s3"; clean "$s3-beside"
chk_silent "deleting a jsonb predicate is silent" \
  "$(nudge l "$(p_edit "$s3" "$t/repo/store.go" "doc->>'k'" 'x := 1')")"
chk_silent "edit beside a jsonb predicate is silent" \
  "$(nudge m "$(p_edit "$s3-beside" "$t/repo/store.go" '// a' '// b' "q := \\\"SELECT doc->>'k'\\\"")")"
clean "$s3"; clean "$s3-beside"

printf "SELECT doc->>'k' FROM t;\n" > "$t/repo/j.sql"
s4="pg-test-path-$$"; clean "$s4"; clean "$s4-2"
chk "path-only payload falls back to the file" "$(nudge n "$(p_path "$s4" "$t/repo/j.sql")")" "pgsql-coding:pgsql-jsonb"
chk "path-only payload says 'this file'"       "$(nudge o "$(p_path "$s4-2" "$t/repo/j.sql")")" "this file touches"
clean "$s4"; clean "$s4-2"

# Delivery channel: Claude Code gets additionalContext (hook_event_name alone is enough);
# Cursor gets a plain line.
s5="pg-test-json-$$"; clean "$s5"
out="$(printf '%s' "$(p_edit "$s5" "$t/repo/q.sql" '' 'CREATE INDEX ON t (a);')" | env -u CLAUDE_PLUGIN_ROOT bash "$here/hooks/skill-nudge.sh")"
chk "hook_event_name delivers additionalContext" "$out" '{"hookSpecificOutput":{"hookEventName":"PostToolUse","additionalContext":'
clean "$s5"
s6="pg-test-cursor-$$"; clean "$s6"
out="$(printf '%s' "$(p_path "$s6" "$t/repo/j.sql")" | env -u CLAUDE_PLUGIN_ROOT bash "$here/hooks/skill-nudge.sh")"
case "$out" in '{'*) fail "nudge is a plain line under Cursor: got JSON '$out'";; *"pgsql-coding:pgsql-jsonb"*) ok "nudge is a plain line under Cursor";; *) fail "nudge is a plain line under Cursor: got '$out'";; esac
clean "$s6"

# --- lint-on-save ------------------------------------------------------------------------------
# A stub squawk on PATH prints gcc-style findings (plus a quote, a backslash and a colour code
# that the hook must escape or strip), so these cases do not depend on a real squawk install.
mkdir -p "$t/bin" "$t/lint/migrations" "$t/nolint"
cat > "$t/bin/squawk" <<'EOF'
#!/usr/bin/env bash
f="${*: -1}"
printf '\033[31m%s:3:1: warning: require-concurrent-index-creation During normal index creation, table updates are blocked "x" \\ y\033[0m\n' "$f"
exit 1
EOF
chmod +x "$t/bin/squawk"
: > "$t/lint/.squawk.toml"; printf 'CREATE INDEX ON t (a);\n' > "$t/lint/migrations/0002.sql"
printf 'CREATE INDEX ON t (a);\n' > "$t/nolint/0002.sql"
lint() { printf '%s' "$1" | PATH="$t/bin:$PATH" bash "$here/hooks/lint-on-save.sh"; }

out="$(lint "$(p_write lint "$t/lint/migrations/0002.sql" 'x')")"; st=$?
[ "$st" -eq 0 ] && ok "lint-on-save exits 0 on findings" || fail "lint-on-save exits 0 on findings: exited $st"
chk "findings reach the model as additionalContext" "$out" '"additionalContext":"› pgsql-coding: squawk reports on 0002.sql'
chk "the finding names the squawk rule"             "$out" "require-concurrent-index-creation"
chk_absent "colour codes are stripped"              "$out" "[31m"
if command -v python3 >/dev/null 2>&1; then
  if printf '%s' "$out" | python3 -c 'import json,sys; json.load(sys.stdin)' 2>/dev/null; then ok "lint-on-save emits valid JSON"; else fail "lint-on-save emits valid JSON: '$out'"; fi
fi
out="$(printf '%s' "$(p_path cur "$t/lint/migrations/0002.sql")" | env -u CLAUDE_PLUGIN_ROOT PATH="$t/bin:$PATH" bash "$here/hooks/lint-on-save.sh")"
case "$out" in '{'*) fail "lint-on-save is plain text under Cursor: got JSON";; *"require-concurrent-index-creation"*) ok "lint-on-save is plain text under Cursor";; *) fail "lint-on-save is plain text under Cursor: got '$out'";; esac
chk_silent "no .squawk.toml means no lint" "$(lint "$(p_write lint "$t/nolint/0002.sql" 'x')")"
chk_silent "non-SQL file is not linted"    "$(lint "$(p_write lint "$t/repo/notes.md" 'x')")"
out="$(CLAUDE_FILE_PATH="$t/lint/migrations/0002.sql" PATH=/nonexistent "$BASH" "$here/hooks/lint-on-save.sh" </dev/null 2>&1)"; st=$?
if [ "$st" -eq 0 ] && [ -z "$out" ]; then ok "lint-on-save is a silent no-op without squawk"; else fail "lint-on-save without squawk: exit $st, output '$out'"; fi

# Can-fail control: prove the helpers fail on bad input, so a broken helper cannot hide a
# regression above. Each probe runs in a subshell with its own fails=0.
probe() { case "$2" in FAIL*) ok "$1";; *) fail "$1: helper did not fail on bad input: '$2'";; esac; }
probe "can-fail: chk_silent rejects output" "$( fails=0; chk_silent p "not-empty" )"
probe "can-fail: chk_absent rejects presence" "$( fails=0; chk_absent p "abc" "b" )"
probe "can-fail: chk rejects absence" "$( fails=0; chk p "abc" "z" )"

[ "$fails" -eq 0 ] || exit 1
