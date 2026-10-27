---
name: pgsql-lint-setup
description: This skill should be used when the user runs /pgsql-lint-setup or asks to "set up squawk", "add SQL linting", "lint our Postgres migrations", "add a migration linter to CI", "fail the build on unsafe migrations" or "scaffold .squawk.toml", or asks how to set squawk's pg_version or assume_in_transaction, how to exclude or ignore a squawk rule, how to run squawk in GitHub Actions, or how to check PL/pgSQL functions with plpgsql_check. It writes the reference .squawk.toml (PostgreSQL 18, migration files assumed to run in a transaction) without overwriting an existing one, and reports the commands for local runs and CI. Not for what a squawk rule means or how to fix the migration (`pgsql-migrations`).
argument-hint: optional target directory (defaults to the repository root)
allowed-tools:
  - Read
  - Write
  - Glob
  - Grep
  - Bash(squawk *)
---

# pgsql-lint-setup: the reference squawk config

> **Write the block below.** It is the same text as `references/squawk.toml` at the plugin root (beside `skills/`). To compare with the shipped file, read `../../references/squawk.toml` from this skill's directory. On Claude Code that file is also `${CLAUDE_PLUGIN_ROOT}/references/squawk.toml`. Do not Glob the user's repository for it.

Scope: write squawk's config into a repository and report how to run it, in one interaction. squawk lints migration files for statements that block reads or writes or break running clients ([squawk rules](https://squawkhq.com/docs/rules)).

Deterministic backstop: `squawk` itself; this skill only configures it.

`$ARGUMENTS` is an optional directory on Claude Code. On Cursor, `argument-hint`, `allowed-tools` and `$ARGUMENTS` are not applied: take an optional directory from the user's message. Default on both hosts is the repository root. Call that directory `$ROOT` below.

## Steps

1. **Do not overwrite an existing config.** squawk walks up from the current directory to find `.squawk.toml` ([squawk CLI](https://squawkhq.com/docs/cli)), so check `$ROOT` and its parents. If one exists, show how it differs from the block below and ask before changing anything.
2. **Find the migration files and the runner.** Glob `**/*.sql` under folders such as `migrations/` or `db/migrations/`. A `-- +goose Up` line marks goose ([goose annotations](https://pressly.github.io/goose/documentation/annotations/)); `{version}_{title}.up.sql` and `.down.sql` pairs mark golang-migrate ([golang-migrate MIGRATIONS.md](https://github.com/golang-migrate/migrate/blob/master/MIGRATIONS.md)). Both wrap a file in a transaction, so keep `assume_in_transaction = true` (the block's comment says when not to).
3. **Write `$ROOT/.squawk.toml`** from the block below. Set `pg_version` as its comment says.
4. **List goose files marked `-- +goose NO TRANSACTION` that lack `-- squawk-disable-assume-in-transaction`.** Report them; do not edit migration files in this command.
5. **Run it once when `squawk` is on PATH:** `squawk 'migrations/*.sql'`, with the glob quoted. Report the count of findings; fixing them is `pgsql-migrations`.
6. **Report the commands** under *Running squawk* and the plpgsql_check line.

## Config to write


```toml
# .squawk.toml: reference config from the pgsql-coding plugin (/pgsql-lint-setup).
# Rules: https://squawkhq.com/docs/rules  Keys: https://squawkhq.com/docs/cli

# Lint as PostgreSQL 18, the plugin's floor; set the major version the
# migrations run on. Version-gated rules follow it: prefer-repack fires from 19.
pg_version = "18"

# goose runs each migration file in one transaction, and golang-migrate sends a
# file as one Exec, which PostgreSQL runs as one implicit transaction. Set false
# when the runner sends each statement on its own. A file that runs outside a
# transaction (goose "-- +goose NO TRANSACTION") carries the comment
# "-- squawk-disable-assume-in-transaction".
assume_in_transaction = true

# No rule is excluded: each default rule backs a pgsql-migrations or pgsql-schema
# rule. Ignore one finding in place with "-- squawk-ignore <rule-id>" instead.
excluded_rules = []
```

## Running squawk

- **Install** with `npm install -g squawk-cli`, `pip install squawk-cli`, or a binary from the [releases page](https://github.com/sbdchd/squawk/releases) ([squawk quick start](https://squawkhq.com/docs/)). Pin an exact version in CI and bump it on purpose, so a new squawk rule cannot fail an unrelated pull request.
- **Run locally:** `squawk 'migrations/*.sql'`; for golang-migrate, `squawk 'migrations/*.up.sql'`, since the down files drop what the up files add. squawk exits non-zero when it reports any violation ([reporter source](https://github.com/sbdchd/squawk/blob/v2.70.0/crates/squawk/src/reporter.rs)).
- **Ignore a finding where it occurs:** `-- squawk-ignore <rule-id>` on the line before the statement, or `-- squawk-ignore-file <rule-id>` for a whole file ([squawk CLI](https://squawkhq.com/docs/cli)). A goose file's `Down` part is linted too; mark an intended drop there. Opt-in rules are switched on with `included_rules`.
- **GitHub Actions:** the action installs `squawk-cli` from npm at `version` (default `latest`) and only comments on the pull request unless `fail-on-violations` is `"true"` ([squawk-action](https://github.com/sbdchd/squawk-action/blob/main/action.yml)):

```yaml
- uses: sbdchd/squawk-action@v2
  with:
    pattern: "migrations/*.sql"
    version: "<exact squawk-cli version>"
    fail-on-violations: "true"
```

## PL/pgSQL functions

squawk does not check function bodies. **plpgsql_check** is a server extension that checks PL/pgSQL bodies against the catalog: unknown columns, wrong types, unused variables, a missing `RETURN`, and, with `security_warnings => true`, `EXECUTE` open to SQL injection ([plpgsql_check](https://github.com/okbob/plpgsql_check)). Install it in the development or CI database, then:

```sql
CREATE EXTENSION plpgsql_check;
SELECT * FROM plpgsql_check_function('public.refresh_totals()', security_warnings => true);
```

The README has queries that check every function and trigger function at once. The Postgres Language Server also lints migrations, with rules inspired by squawk; its CLI is `postgres-language-server check <file>` and its config `postgres-language-server.jsonc` ([getting started](https://pg-language-server.com/latest/getting_started/)). Keep squawk as the CI gate so the advice in `pgsql-migrations` matches the tool.

## Sources

- squawk CLI and `.squawk.toml` keys (`pg_version`, `assume_in_transaction`, `excluded_rules`, `included_rules`, `excluded_paths`): <https://squawkhq.com/docs/cli> (checked 2026-10-27; squawk v2.70.0, released 2026-10-15)
- squawk quick start and rules: <https://squawkhq.com/docs/>, <https://squawkhq.com/docs/rules> (checked 2026-10-27)
- squawk source at v2.70.0, opt-in rules, default `pg_version`, the `prefer-repack` version gate, exit code: <https://github.com/sbdchd/squawk/tree/v2.70.0/crates> (checked 2026-10-27)
- squawk-action inputs: <https://github.com/sbdchd/squawk-action/blob/main/action.yml> (checked 2026-10-27; action v2.2.0)
- goose annotations: <https://pressly.github.io/goose/documentation/annotations/> (checked 2026-10-27)
- golang-migrate file naming and PostgreSQL driver: <https://github.com/golang-migrate/migrate/blob/master/MIGRATIONS.md>, <https://github.com/golang-migrate/migrate/blob/master/database/postgres/README.md> (checked 2026-10-27)
- plpgsql_check README, PostgreSQL 14 to 20 supported: <https://github.com/okbob/plpgsql_check> (checked 2026-10-27; v2.10.16)
- Postgres Language Server getting started: <https://pg-language-server.com/latest/getting_started/> (checked 2026-10-27; v0.28.2)
