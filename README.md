# PostgreSQL Coding Plugin

[![License: MIT](https://img.shields.io/badge/License-MIT-blue.svg)](LICENSE)
[![Version](https://img.shields.io/badge/version-0.1.0-blue)](CHANGELOG.md)
[![Claude Code](https://img.shields.io/badge/Claude_Code-plugin-D97757?logo=anthropic&logoColor=white)](https://docs.claude.com/en/docs/claude-code/overview)
[![Cursor](https://img.shields.io/badge/Cursor-plugin-000?logo=cursor&logoColor=white)](https://cursor.com)
[![Keep a Changelog](https://img.shields.io/badge/Keep%20a%20Changelog-1.1.0-E05735)](CHANGELOG.md)

An AI plugin by **Cadasto B.V.** that teaches AI coding assistants how to write, review, tune and debug SQL for PostgreSQL: queries, `json` and `jsonb` with the SQL/JSON functions, schema design, indexing, plan analysis, and migrations that do not lock a live table. It is for anyone who has an assistant work on a PostgreSQL-backed application, especially from Go (pgx) or PHP (PDO). It adds eight skills, two report-only agents (a SQL reviewer and an `EXPLAIN` plan analyst), and three hooks for **[Claude Code](https://docs.claude.com/en/docs/claude-code/overview)** and **[Cursor](https://cursor.com)** from one shared component set, plus a Cursor rule.

The plugin owns the judgement layer. The deterministic checks stay with the tools: `EXPLAIN (ANALYZE, BUFFERS)` decides whether an index or a rewrite helps, [squawk](https://squawkhq.com) decides whether a migration takes a dangerous lock, and [plpgsql_check](https://github.com/okbob/plpgsql_check) checks PL/pgSQL. Each skill names the tool that settles a rule and cites the source a judgement comes from, mostly the [PostgreSQL 18 manual](https://www.postgresql.org/docs/18/index.html).

**Requirements.** A Claude Code or Cursor host. The plugin is Markdown, JSON and three shell hooks, with no build step and no MCP server. The guidance targets **PostgreSQL 18** (PostgreSQL 19 additions are flagged as hints until it is released). The hooks use `squawk` when it is installed; `psql`, a PostgreSQL 18 test database, and the `plpgsql_check` extension make the skills' evidence steps possible. See [Host toolchain](docs/install.md#host-toolchain).

## Table of contents

- [Features](#features)
- [Installation](#installation)
- [Components](#components)
- [Using with Go and PHP](#using-with-go-and-php)
- [Using with subagent orchestrators](#using-with-subagent-orchestrators)
- [Development](#development)
- [Documentation](#documentation)
- [License](#license)

## Features

- **Routing**: the auto-invoked `pgsql-coding` router names the tool that settles a question and the focused skill that owns it.
- **Focused standards**: `pgsql-query`, `pgsql-jsonb`, `pgsql-schema`, `pgsql-indexing`, `pgsql-performance` and `pgsql-migrations` load on use. Each keeps its rules short and puts the detail in reference files that load only when a task needs them, every rule with its source.
- **jsonb in depth**: operators against the SQL/JSON functions (`JSON_TABLE`, `JSON_VALUE`, jsonpath), which GIN or expression index serves which predicate, when to promote a key to a column, and how jsonb values cross pgx and PDO.
- **Evidence first**: plan reading, planner statistics, `pg_stat_statements`, `auto_explain`, lock waits, and the rule that no index or rewrite is proposed without a plan.
- **Safe migrations**: lock levels, `lock_timeout`, `CONCURRENTLY`, `NOT VALID` then `VALIDATE`, mapped to squawk rule ids; `/pgsql-lint-setup` writes the reference `.squawk.toml`.
- **Plan analysis**: a summariser script reads a TEXT or JSON plan and points at the node where a row-estimate error starts, spills, loop counts and filter waste; the `pgsql-plan-analyst` agent takes a long plan, or a before-and-after pair, and returns a ranked diagnosis without filling the conversation.
- **Review**: the report-only `pgsql-reviewer` agent returns severity-ranked findings on SQL in `.sql` files, migrations, and Go or PHP query strings.
- **Hooks**: a session-start line in PostgreSQL workspaces, squawk findings after a migration edit (`lint-on-save`, opt-in through `.squawk.toml`), and a nudge to the one skill an edit calls for (`skill-nudge`).
- **Cursor parity**: Cursor gets the same skills, agent and hooks, plus `rules/pgsql-context.mdc` mirroring the router.

## Installation

**Claude Code**, from the Cadasto marketplace (once listed there):

```text
/plugin marketplace add Cadasto/plugin-marketplace
/plugin install pgsql-coding@cadasto
```

Or load a local working copy for a single session: `claude --plugin-dir /path/to/pgsql-coding-plugin`.

**Cursor**: add this repository as a plugin (Settings → Plugins, from a Git URL or a local path). The repo includes a Cursor manifest at [`.cursor-plugin/plugin.json`](.cursor-plugin/plugin.json); skills, agents, references and hook scripts are shared with the Claude plugin.

See [docs/install.md](docs/install.md) for marketplace, local-development, update, Cursor and toolchain details.

## Components

| Component | Purpose |
|-----------|---------|
| Skill `pgsql-coding` | Auto-invoked router: sends each PostgreSQL topic to the tool that settles it and the focused skill that owns it. Its `versions.md` reference lists what needs PostgreSQL 17, 18 or 19. |
| Skill `pgsql-query` | Writing and reviewing statements: NULL semantics, joins, CTEs, window functions, keyset pagination, upsert, `MERGE`, `RETURNING`, transactions and row locks, injection-safe binding, pgx v5 and PDO, testing against a real server. |
| Skill `pgsql-jsonb` | `json` vs `jsonb`, operators, SQL/JSON constructors and query functions, `JSON_TABLE`, jsonpath, modification and aggregation, GIN and expression indexes, modelling, and the pgx and PDO mapping. |
| Skill `pgsql-schema` | Types, identity and `uuidv7()` keys, constraints (temporal, `NOT ENFORCED`), generated columns, partitioning, functions and triggers, privileges and row-level security. |
| Skill `pgsql-indexing` | Index types and operator classes, column order and skip scan, partial, expression and covering indexes, and finding unused, duplicate or invalid indexes. |
| Skill `pgsql-performance` | Reading `EXPLAIN` plans, planner statistics, generic vs custom plans, `pg_stat_statements`, `auto_explain`, waits and locks, and the rewrites the evidence justifies. Ships `scripts/plan-summary.py`, which summarises a TEXT or JSON plan. |
| Skill `pgsql-migrations` | Changing a live schema safely: lock levels, `lock_timeout`, `CONCURRENTLY`, `NOT VALID` then `VALIDATE`, expand and contract, batched backfills, each mapped to its squawk rule. |
| Skill `/pgsql-lint-setup` | User-invoked: writes the reference `.squawk.toml` and says how to run squawk locally and in CI. Never overwrites an existing config unprompted. |
| Agent `pgsql-reviewer` | Report-only, context-isolated SQL reviewer. Loads the skills, returns severity-ranked findings, never edits files or runs DML, and dispatches no sub-agents. |
| Agent `pgsql-plan-analyst` | Report-only, context-isolated `EXPLAIN` analyst for a long plan or a before-and-after pair. Runs the plan summariser, reads only the flagged nodes, and returns where the time goes, where an estimate error starts, and the command that confirms each fix. |
| Session-start hook | Detects PostgreSQL use (pgx or lib/pq in `go.mod`, `ext-pdo_pgsql` in `composer.json`, a postgres image in a compose file, or a `*.sql` file) and prints one standards line; dual-host. |
| Lint-on-save hook | After a `*.sql` edit, runs squawk on that file when the project has a `.squawk.toml` and squawk is installed, and hands the findings to the model; wired for both hosts (on Cursor, delivery is unverified: [install.md](docs/install.md#hooks)); never blocks an edit. |
| Skill-nudge hook | After a `.sql`, `.go` or `.php` edit, names the one focused skill the added text calls for, once per skill per session; wired for both hosts (on Cursor, delivery is unverified: [install.md](docs/install.md#hooks)). |
| Squawk config `references/squawk.toml` | The reference squawk configuration `/pgsql-lint-setup` writes. |
| Cursor rule `pgsql-context.mdc` | `**/*.sql`-scoped guidance mirroring the router for Cursor. |

## Using with Go and PHP

SQL usually lives inside Go or PHP code, so a change often needs two plugins. This plugin owns the SQL text, the schema, and the driver boundary (placeholders, scanning, jsonb values, batching, error codes); [go-coding](https://github.com/Cadasto/go-coding-plugin) and php-coding own the host language. Install them side by side. A Go change that adds a jsonb query loads `go-coding` for the Go and `pgsql-jsonb` plus `pgsql-query` for the SQL.

## Using with subagent orchestrators

Subagents do not inherit the parent session's skills. A plan runner that dispatches implementers and reviewers must tell them, in every brief, to load the skills:

- **Implementer brief**: "Before writing SQL, invoke the Skill tool with `pgsql-coding:pgsql-coding`, then the focused skills matching the change (see its *Route, then load* table). Run squawk on migration files. Run `EXPLAIN` only against the database named here: <database>."
- **Reviewer brief**: "Before reading the diff, load `pgsql-coding:pgsql-coding` plus the focused skills the diff calls for; cite the rule a finding rests on. Do not dispatch `pgsql-reviewer`: you are the review seat."

Use `pgsql-reviewer` directly when no such seat exists, as with an ad-hoc "review this migration" request.

## Development

The plugin has no build step. Validate locally:

```bash
./scripts/validate.sh                    # manifests, parity, frontmatter, references, routing surface, docs, evals
python3 scripts/validate.py --selftest   # proves each check still catches its failure case
./scripts/hooks-test.sh                  # bash tests for the three hooks
python3 scripts/plan-summary-test.py     # the plan summariser against real PostgreSQL 18 plans
claude plugin validate .                 # manifest + component structure
```

[docs/testing.md](docs/testing.md) defines each check and the eval suite.

## Documentation

- [docs/install.md](docs/install.md): install on both hosts, and the tools the hooks and skills use
- [docs/testing.md](docs/testing.md): validate, test the hooks, run the evals, test triggering
- [docs/versioning.md](docs/versioning.md): SemVer policy, release steps, moving the PostgreSQL floor
- [docs/authoring.md](docs/authoring.md): component conventions and the source registry for refreshing the standards

See [AGENTS.md](AGENTS.md) for contributor conventions.

## License

[MIT](LICENSE)

PostgreSQL is a registered trademark of the PostgreSQL Community Association of Canada. This plugin is an independent project for use with PostgreSQL and is not affiliated with or endorsed by the PostgreSQL project.
