#!/usr/bin/env bash
# PostToolUse / afterFileEdit hook (host-agnostic): lint the just-edited .sql file with squawk.
#
# Opt-in by the project: runs only when a .squawk.toml exists in the file's directory or a parent
# (the file /pgsql-lint-setup writes) and squawk is on PATH. Squawk's rules target migration
# safety, so a project without that config would mostly see noise. Findings go back to the model
# as hookSpecificOutput.additionalContext (Claude Code) or plain lines (Cursor). ALWAYS exits 0;
# it reports and never blocks an edit.
#
# File-path resolution, in order:
#   1. $CLAUDE_FILE_PATH          — explicit override for tests and manual runs; no host sets it.
#   2. tool payload JSON on stdin — Claude (`tool_input.file_path`) or Cursor `afterFileEdit`
#      (`file_path`). Extracted without a jq/python dependency.
set -u

# Cheapest exit first: without squawk there is nothing to do, so do not even read the payload.
command -v squawk >/dev/null 2>&1 || exit 0

f="${CLAUDE_FILE_PATH:-}"; payload=""
if [ ! -t 0 ]; then
  payload="$(cat)"
  [ -n "$f" ] || f="$(printf '%s' "$payload" \
        | grep -oE '"file_?[Pp]ath"[[:space:]]*:[[:space:]]*"[^"]+"' \
        | head -n1 \
        | sed -E 's/.*"([^"]+)"$/\1/')"
fi

[ -n "$f" ] || exit 0
case "$f" in *.sql) ;; *) exit 0 ;; esac
[ -f "$f" ] || exit 0

# Walk up from the file's directory to the nearest .squawk.toml; stop at the filesystem root.
dir="$(cd "$(dirname "$f")" 2>/dev/null && pwd)" || exit 0
cfgdir=""
while [ -n "$dir" ]; do
  [ -f "$dir/.squawk.toml" ] && { cfgdir="$dir"; break; }
  [ "$dir" = "/" ] && break
  dir="$(dirname "$dir")"
done
[ -n "$cfgdir" ] || exit 0

# squawk walks up from its working directory to find .squawk.toml; run it from the config's
# directory so the project's settings apply. The gcc reporter prints one line per violation.
abs="$(cd "$(dirname "$f")" && pwd)/$(basename "$f")"
out="$(cd "$cfgdir" && squawk --reporter gcc "$abs" 2>&1)" || true
esc="$(printf '\033')"
out="$(printf '%s\n' "$out" | sed -e "s/${esc}\[[0-9;]*m//g" | grep -E ':[0-9]+:[0-9]+:' | head -n 20)"
[ -n "$out" ] || exit 0

msg="› pgsql-coding: squawk reports on $(basename "$f"); load pgsql-coding:pgsql-migrations and fix or justify each line:"
if [ -n "${CLAUDE_PLUGIN_ROOT:-}" ] || printf '%s' "$payload" | grep -q '"hook_event_name"'; then
  # Claude Code: build the JSON string by hand (no jq). Escape backslashes and quotes, turn tabs
  # and newlines into escapes, and drop any other control character squawk might print.
  body="$(printf '%s\n%s' "$msg" "$out" \
    | tr -d '\000-\010\013-\037' \
    | sed -e 's/\\/\\\\/g' -e 's/"/\\"/g' -e 's/	/\\t/g' \
    | awk 'NR > 1 { printf "\\n" } { printf "%s", $0 }')"
  printf '{"hookSpecificOutput":{"hookEventName":"PostToolUse","additionalContext":"%s"}}\n' "$body"
else
  printf '%s\n%s\n' "$msg" "$out"                # Cursor afterFileEdit: plain lines
fi
exit 0
