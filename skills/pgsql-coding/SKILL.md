---
name: pgsql-coding
description: PostgreSQL coding-standards router for PostgreSQL 18 and later (19 additions flagged as hints). This skill should be used when a task writes, reviews, tunes or debugs SQL, a .sql file, a migration, a schema, or a query string in Go (pgx) or PHP (PDO) code, when the task spans several areas, or when the question is which tool or standard applies. It names the deterministic tool to run (EXPLAIN, squawk, plpgsql_check), then the focused skill that owns the topic (pgsql-query, pgsql-jsonb, pgsql-schema, pgsql-indexing, pgsql-performance, pgsql-migrations, pgsql-lint-setup). Loading the router alone does not apply the standards; load the skill it names next. For one already-identified topic, load that skill directly. Not for other databases (MySQL, SQLite, SQL Server) and not for Go or PHP style, which go-coding and php-coding own.
---

# pgsql-coding: PostgreSQL standards router

Route the PostgreSQL task to the skill and the tool that own it. This skill is an index, not the standard. Two principles drive it:

- **Evidence beats reasoning.** A plan from `EXPLAIN (ANALYZE, BUFFERS)` decides whether an index or a rewrite helps. `squawk` decides whether a migration takes a dangerous lock. `plpgsql_check` finds PL/pgSQL errors before run time. Run the tool; the skills hold the judgment the tools cannot supply.
- **The floor is PostgreSQL 18.** Write PG 18 forms with no fallback for older servers. PostgreSQL 19 additions are hints until the project's server runs 19. When a project pins an older server, say which suggestion needs 18 ([versions.md](references/versions.md) lists them) instead of writing a statement that will not run there.

## Routing table

| Topic | Run now (deterministic) | Skill |
|---|---|---|
| Writing or reviewing a statement: NULLs, joins, CTEs, window functions, pagination, upsert, `MERGE`, `RETURNING`, `COPY`, transactions, row and advisory locks, pgx or PDO binding, N+1 loops, tests | the test suite against a real PostgreSQL 18 | `pgsql-query` |
| `json` and `jsonb` columns, `->`, `->>`, `@>`, jsonpath, `JSON_TABLE`, `JSON_VALUE`, jsonb indexes, JSON values in Go or PHP | `EXPLAIN` the predicate to see whether the index is used | `pgsql-jsonb` |
| Tables, column types, keys, constraints, generated columns, `CREATE TYPE`, `CREATE DOMAIN`, views, partitions, functions and PL/pgSQL (dynamic SQL included), triggers, roles, row-level security | `plpgsql_check` for PL/pgSQL; `squawk` on the DDL | `pgsql-schema` |
| Which index, column order, partial, expression or covering indexes, GIN, GiST, BRIN, `pg_trgm`, `text_pattern_ops`, unused, duplicate or invalid indexes (`pg_stat_user_indexes`, `pg_index`) | `EXPLAIN (ANALYZE, BUFFERS)` before and after; HypoPG for a what-if | `pgsql-indexing` |
| A slow query, reading a plan, planner statistics, `CREATE STATISTICS`, generic plans and `plan_cache_mode`, `pg_stat_statements`, `pg_stat_activity`, `auto_explain`, lock waits, bloat | `EXPLAIN (ANALYZE, BUFFERS)`; `pg_stat_statements` | `pgsql-performance` |
| A migration file, `ALTER TABLE` on a live table, `CREATE INDEX CONCURRENTLY`, `REINDEX CONCURRENTLY`, `NOT VALID` and `VALIDATE`, `ALTER TYPE ... ADD VALUE`, lock timeouts, backfills | `squawk <migration files>` | `pgsql-migrations` |
| `.squawk.toml`, adding SQL linting to a repository or CI | none | `/pgsql-lint-setup` |
| Which server version a feature needs | `SHOW server_version;` | [versions.md](references/versions.md) |

## Route, then load

Before writing or reviewing SQL, load the focused skill that matches the change with the Skill tool (`pgsql-coding:pgsql-jsonb`, and so on). Do not work from memory of it.

| The change touches | Load |
|---|---|
| a query in a `.sql` file or a SQL string in `.go` or `.php` code, `JOIN`, `GROUP BY`, `ON CONFLICT`, `MERGE`, `COPY`, `FOR UPDATE`, `pg_advisory_*`, a transaction, `pgx.`, `pgxpool.`, `PDO` | `pgsql-query` |
| `jsonb`, `json`, `->`, `->>`, `@>`, `@?`, a `jsonb_*` or `JSON_*` function, `json.RawMessage` in a scan | `pgsql-jsonb` |
| `CREATE TABLE`, a column type, `CONSTRAINT`, `REFERENCES`, `GENERATED`, `PARTITION`, `CREATE TYPE`, `CREATE DOMAIN`, `CREATE VIEW`, `CREATE FUNCTION`, `EXECUTE format(`, `CREATE TRIGGER`, `POLICY`, `GRANT` | `pgsql-schema` |
| `CREATE INDEX`, `USING gin`, `gist` or `brin`, `INCLUDE`, a partial index, `gin_trgm_ops`, `text_pattern_ops`, `pg_stat_user_indexes`, `indisvalid` | `pgsql-indexing` |
| `EXPLAIN` output, "slow", `pg_stat_statements`, `pg_stat_activity`, `auto_explain`, `CREATE STATISTICS`, `plan_cache_mode`, a lock wait, a statement timeout | `pgsql-performance` |
| a file in a migrations folder, `ALTER TABLE`, `ALTER TYPE`, `DROP`, `RENAME`, `CONCURRENTLY`, `NOT VALID`, `VALIDATE CONSTRAINT`, `lock_timeout`, a backfill | `pgsql-migrations` |

One load per skill per session is enough. A change usually needs two skills: a new jsonb query needs `pgsql-jsonb` and `pgsql-query`; a new index in a migration needs `pgsql-indexing` and `pgsql-migrations`. SQL inside Go or PHP code also needs that language's plugin (`go-coding`, `php-coding`) for the host code.

Subagents do not inherit loaded skills. An orchestrator that dispatches implementers or reviewers puts this table in every brief, with the database the subagent may query, if any.

## Running SQL against a database

- **Ask before touching a database.** Use `psql` or a connected PostgreSQL MCP server only against a database the user names, such as a local container or a test database. Never against production without the user's explicit consent.
- **`EXPLAIN ANALYZE` executes the statement.** Plain `EXPLAIN` does not. Wrap an `INSERT`, `UPDATE`, `DELETE` or `MERGE` in `BEGIN; EXPLAIN (ANALYZE, BUFFERS) ...; ROLLBACK;` ([EXPLAIN](https://www.postgresql.org/docs/18/sql-explain.html)).
- **Plans need realistic data.** A plan on a ten-row development table says nothing about a ten-million-row production table. Say how much data the plan ran on.

## Minimum checklist (when a second load is not affordable)

- Bind every value as a parameter. An identifier that comes from input goes through an allowlist. Never format values into SQL text.
- Use `NOT EXISTS`, not `NOT IN (subquery)`; use `IS DISTINCT FROM` when two NULLs must compare equal.
- Give every `LIMIT` an `ORDER BY` that is unique. Page with a keyset (`WHERE (a, b) > ($1, $2)`), not a growing `OFFSET`.
- Use `timestamptz`, `text`, `bigint GENERATED ALWAYS AS IDENTITY` or `uuidv7()`, and `numeric` for money. Index the referencing columns of a foreign key.
- For jsonb, index the predicate shape the query uses: `@>` with a GIN index, `->>` with an expression index. Promote a key that every row has and every query filters on to a real column.
- Propose no index or rewrite without a plan: `EXPLAIN (ANALYZE, BUFFERS)` before and after.
- In migrations, set `lock_timeout`, build indexes `CONCURRENTLY`, add constraints `NOT VALID` and validate them separately, and run `squawk`.

## Tie-breaks (when two valid forms compete)

When two forms return the same rows and both pass the tools, decide by: correct under NULLs and concurrent writes, then the measured plan on realistic data, then the form the PostgreSQL manual documents for that purpose, then the shorter statement. Say which of these decided it; "more idiomatic" alone is not a reason.

## Writing for the human

Anything a person reads, such as a PR description, a review comment or a question, goes in plain English. State the effect before the mechanism: "the second page repeats rows when two orders share a timestamp", not "non-unique sort key". Expand a term the first time it appears or leave it out. Keep SQL, identifiers, commands and setting names verbatim; only the prose around them must be plain.

## Authoritative sources (cite, don't guess)

- PostgreSQL 18 manual: <https://www.postgresql.org/docs/18/index.html>; release notes 18: <https://www.postgresql.org/docs/18/release-18.html>; release notes 19 (hints): <https://www.postgresql.org/docs/19/release-19.html>
- PostgreSQL wiki, "Don't Do This": <https://wiki.postgresql.org/wiki/Don%27t_Do_This>
- pgx v5: <https://pkg.go.dev/github.com/jackc/pgx/v5>; PHP PDO PostgreSQL driver: <https://www.php.net/manual/en/ref.pdo-pgsql.php>
- squawk rules: <https://squawkhq.com/docs/rules>; plpgsql_check: <https://github.com/okbob/plpgsql_check>

## For a focused review or a long plan

Dispatch the `pgsql-reviewer` agent. It is report-only and context-isolated: it loads these skills, reads SQL in `.sql` files, migrations and Go or PHP query strings, and returns severity-ranked findings. If a workflow already owns the reviewer seat, that reviewer loads the focused skills itself instead; one review seat per change.

Dispatch the `pgsql-plan-analyst` agent for an `EXPLAIN` plan over about 50 lines or two plans to compare, with the plan saved to a file. It runs `pgsql-performance`'s plan summariser in its own context and returns a ranked diagnosis, so the plan never fills this conversation.

`/pgsql-lint-setup` writes the reference `.squawk.toml` into a repository.
