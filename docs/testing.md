# Testing and validation

This page is for contributors checking a change before review: what each validator proves, the hook tests, the eval suite, and the manual triggering tests on both hosts. The plugin is JSON manifests, Markdown components, three shell hooks, a reference squawk config, and a Python validator. There is no build step.

## Validation

```bash
./scripts/validate.sh                       # the structural checks below (soft-skips without python3)
python3 scripts/validate.py --selftest      # proves each check still catches its failure case (CI runs it)
python3 scripts/validate.py --check-links   # every cited URL resolves (needs the network)
./scripts/hooks-test.sh                     # bash tests for the three hooks
python3 scripts/plan-summary-test.py        # the plan summariser against real PostgreSQL 18 plans
claude plugin validate .                    # manifest and component structure (no Python needed)
```

`scripts/validate.py` checks:

- **Manifests**: both parse, carry `name`, `version`, `description` and an `author` object, agree on `name`, `version`, `description`, `author`, `license`, `repository` and `keywords`, and every declared path exists.
- **Hooks**: both configs exist and parse; every `hooks/*.sh` is wired for the equivalent event on both hosts (`SessionStart`/`sessionStart`, `PostToolUse`/`postToolUse`), exists, and is executable; Claude Code commands reach their script through `${CLAUDE_PLUGIN_ROOT}`, Cursor commands never use it, the Cursor config carries `"version": 1`, and each edit hook's matcher names the host's edit tools (`Write|Edit`, `Write|StrReplace`).
- **Frontmatter**: `name` equals the directory or filename, descriptions fit 1,024 characters (a folded `>-` or literal `|` block measured whole), no unquoted `: ` or ` #`, and agents declare `tools:`, never `allowed-tools:`.
- **Progressive disclosure**: every `skills/*/references/*.md` is linked from its `SKILL.md` and every link resolves; references carry no frontmatter, open with `## Contents` past 100 lines, stay under 200 lines, and end with `## Sources`. A `SKILL.md` body stays under 1,500 words.
- **Routing surface**: the router, `rules/pgsql-context.mdc`, the session-start banner and `pgsql-reviewer` each name every focused skill.
- **Doc inventories**: README.md, AGENTS.md and this page name every shipped skill, agent and hook; docs/install.md names every hook.
- **Tie-break sentence**: identical in the router, the Cursor rule and the agent.
- **Squawk scaffold**: the toml block in `pgsql-lint-setup` is byte-identical to `references/squawk.toml`.
- **Evals**: each case has a `prompt.md` and graders with frontmatter; a skill-fired grader names a shipped skill; a read-reference grader names a reference that exists.

CI (`.github/workflows/validate.yml`) runs the validator, `--selftest`, the hook tests and the plan-summary tests on every pull request and on pushes to `main`. `.github/workflows/links.yml` runs `--check-links` weekly and on pull requests that touch cited files.

## Hook tests

`scripts/hooks-test.sh` covers all three hooks with real host payload shapes:

- `session-start`: detection by `go.mod` (pgx or lib/pq), `composer.json` (`ext-pdo_pgsql`), a compose file with a postgres image, or a `*.sql` file; silence elsewhere; the `/pgsql-lint-setup` hint only without a `.squawk.toml`; exit 0; the Claude Code line naming skills only; under Cursor, the workspace in `CURSOR_PROJECT_DIR` inspected rather than the plugin directory, every skill listed with the install path, and valid JSON `additional_context`, even with a quote in that path.
- `skill-nudge`: one skill per edit, chosen from the text the edit adds (not the deleted text or the tool response echo) in Claude Code's payload and in Cursor's `StrReplace` `new_string`, including a keyword on a later line of a multi-line edit; the whole file when a Cursor payload has no added-text field; a relative Cursor path joined to `CURSOR_PROJECT_DIR` and an absolute one left as is; once per skill per session (`session_id` or `conversation_id`); `hookSpecificOutput.additionalContext` under Claude Code (`pgsql-coding:<skill>`), `additional_context` under Cursor (the skill's install path, JSON-escaped), both valid JSON.
- `lint-on-save`: a stub `squawk` on PATH proves the findings reach the model as valid JSON on both hosts with colour codes stripped, Claude Code told `pgsql-coding:pgsql-migrations` and Cursor the skill's install path, a relative Cursor path linted under `CURSOR_PROJECT_DIR`, that nothing runs without a `.squawk.toml` or without squawk, and that the hook always exits 0.

## Plan summariser tests

`scripts/plan-summary-test.py` runs `skills/pgsql-performance/scripts/plan-summary.py` on plans captured from `EXPLAIN (ANALYZE, BUFFERS)` on a `postgres:18` (18.6) container, in TEXT and JSON (`scripts/testdata/plans/`). It checks that every plan captured in both formats gives the same node names and findings, as does psql's aligned output; that an estimate error is reported where it starts and where it grows rather than at every ancestor, never where a `LIMIT` or a semi join stopped a node early, never on the planner's one-row floor, and with fractional row counts compared as they are; that sort, incremental-sort, hash, hash-aggregate and stored-row spills, loop counts, filter and join-filter waste, heap fetches (a total, not per loop), JIT share and an estimates-only plan are recognised; and that a `TIMING OFF` plan is summarised without a ranking by time. To add a case, capture a new plan the same way and assert on its findings.

To try `lint-on-save` against a real squawk, install it (see [install.md](install.md#host-toolchain)) and edit a migration in a repository that has a `.squawk.toml`.

## Eval suite

`evals/` holds cases for `claude plugin eval` ([plugin evals](https://code.claude.com/docs/en/plugin-evals)). Each case runs with and without the plugin and reports both scores and the difference. Each case has three graders: an `llm` grader with concrete PASS and FAIL conditions, a `tool_used` grader that checks the focused skill fired, and a `regex` grader over the trace (`arm: with-only`) that checks the right reference was read.

```bash
claude plugin eval . --trust-plugin                              # the whole suite, with a no-plugin baseline
claude plugin eval . --trust-plugin --case 'jsonb-*' --runs 1    # one quick pass while editing a case
claude plugin eval . --trust-plugin --ablation none              # with-plugin arm only, half the cost
```

Every run is a full Claude session on your own credential, so the whole suite costs real model calls. Results land in `evals/results/`, which is gitignored.

## Local triggering tests

Load a working copy (see [install.md](install.md)), then, in a repository that uses PostgreSQL:

- **Session-start hook**: one standards line prints, naming the floor, the skills and `pgsql-reviewer`.
- **`pgsql-coding` router**: ask which standard applies to a mixed change; it names a tool and the focused skill.
- **Focused skills**: each of these loads its skill and reads a reference (the transcript shows the `Read`):
  - a jsonb containment query or a `JSON_TABLE` question loads `pgsql-jsonb`;
  - "which index for this query" loads `pgsql-indexing`;
  - a pasted `EXPLAIN (ANALYZE, BUFFERS)` plan loads `pgsql-performance`;
  - a keyset pagination or upsert question, or a pgx or PDO query, loads `pgsql-query`;
  - a new table with keys and constraints loads `pgsql-schema`;
  - adding a NOT NULL column or a foreign key to a large live table loads `pgsql-migrations`.
- **`pgsql-reviewer`**: a review request loads the skills, returns severity-ranked findings, and does not edit files, run DML, or spawn agents.
- **`pgsql-plan-analyst`**: a before-and-after pair of plans, or one plan over about 50 lines, is handed to the agent; it runs `plan-summary.py`, returns at most five ranked items with a confirming command each, and edits nothing.
- **`/pgsql-lint-setup`**: writes `.squawk.toml` and does not overwrite an existing one unprompted.
- **`skill-nudge` and `lint-on-save` hooks**: edit a `.sql` file that adds a jsonb predicate and confirm the `pgsql-jsonb` nudge; edit a migration with `CREATE INDEX` (no `CONCURRENTLY`) in a repository with a `.squawk.toml` and confirm the squawk finding arrives.
- **Cursor rule**: open a `.sql` file and confirm `pgsql-context.mdc` attaches.
- **Cursor hooks**: in a PostgreSQL workspace other than this repository, confirm the session-start line reaches the agent (it names the skills' install path) and that both a new `.sql` file (`Write`) and an edit of an existing one (`StrReplace`) trigger the nudge. `afterFileEdit` is not the event: it documents no output, so the nudge would not reach the model.
- **Cursor agents**: ask `pgsql-reviewer` to fix the file it reviewed and confirm it refuses, which shows `permissionMode: readonly` is honoured; then confirm it read a skill from the path the brief gave.

After editing content, reinstall or restart the session.
