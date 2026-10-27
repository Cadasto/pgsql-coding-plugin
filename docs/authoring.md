# Skill, reference, agent, and rule authoring conventions

This page is for contributors adding or changing a skill (including a slash-command skill), a reference, the agent, or the Cursor rule, and for anyone refreshing the skills against current PostgreSQL practice. It expands on the *how* behind [AGENTS.md](../AGENTS.md), which stays authoritative, and it holds the source registry a refresh re-reads. The shipped components are the reference examples.

## Naming and layout

- **Components are kebab-case** and namespaced `<plugin>:<component>` (for example `pgsql-coding:pgsql-jsonb`). A component's frontmatter `name` MUST equal its directory (skills) or filename stem (agents); `scripts/validate.py` enforces this.
- `skills/<name>/SKILL.md` with its topic files in `skills/<name>/references/<topic>.md` · `agents/<name>.md` · `rules/<name>.mdc` · `evals/<case>/`. The shipped squawk config lives in the top-level `references/squawk.toml`, a different directory from a skill's `references/`. The legacy `commands/` layout is not used.

## Skill, reference, agent, or rule

- **Router skill** (`pgsql-coding`): auto-invoked; names the tool to run and the focused skill to load. It holds no rules beyond the minimum checklist. Its one reference, `versions.md`, says which feature needs PostgreSQL 17, 18 or 19.
- **Focused skill** (`pgsql-query`, `pgsql-jsonb`, `pgsql-schema`, `pgsql-indexing`, `pgsql-performance`, `pgsql-migrations`): load-on-use. `SKILL.md` carries the rules most tasks need and a table that routes to its references. This follows the progressive-disclosure pattern in Anthropic's [skill authoring best practices](https://platform.claude.com/docs/en/agents-and-tools/agent-skills/best-practices): the description is always on, the body loads on use, and a reference costs nothing until it is read.
- **Command skill** (`/pgsql-lint-setup`): a thin one-shot `SKILL.md` with `argument-hint` and `allowed-tools`, using `$ARGUMENTS` in the body.
- **Agent** (`pgsql-reviewer`): a context-isolated specialist. Use **`tools:`**, **never** `allowed-tools:`, which an agent file ignores, so the agent silently inherits *all* tools. Include `Skill` in `tools:` so the agent can load the skills, because a subagent does not inherit the parent's loaded skills.
- **Cursor rule** (`rules/pgsql-context.mdc`): a Cursor-only `.mdc` with `description`, `globs` and `alwaysApply` that mirrors the router.

## The `description` (the trigger)

The description is the only always-on text, so it carries the trigger words: third person ("This skill should be used when ..."), what it covers, the concrete operators, functions, keywords and situations that should load it, and a short "Not for ..." naming the sibling skill that owns the neighbouring topic. The Agent Skills limit is 1,024 characters; `scripts/validate.py` enforces it.

**YAML gotcha:** a `description` value with an unquoted `: ` (colon-space) or ` #` is invalid YAML (YAML 1.2.2, section 7.3.3), so the component loads with empty metadata. `scripts/validate.py` guards against it; `claude plugin validate` does not. Reword or quote the value.

## Body and reference shape

- **`SKILL.md`**: `# <name>: <title>`, a one-line scope, a `Deterministic backstop:` line, `## Rules` (bullets with a bold lead and an inline source link), a `## Read the reference` table (`| The task involves | Read |`), and `## Sources`. Keep the body under 1,500 words.
- **Reference file**: no frontmatter. `# Title`, a `Read when:` line, a backstop line, `## Contents` past 100 lines, `## Rules` as bullets with a bold lead and an inline link, short SQL examples, an optional `## Newer in PostgreSQL 19 (hints)`, and `## Sources` with a "(checked YYYY-MM-DD)" mark on each entry. Keep it under 200 lines; split it before then.
- **Version annotations.** The floor is PostgreSQL 18, so PG 18 forms are written flat, with no fallback for older servers. A "(PG 15)" annotation is provenance. A PostgreSQL 19 feature appears only under `## Newer in PostgreSQL 19 (hints)` until 19 is released.
- **Style.** Plain English, imperative, short sentences, no second person, no em dashes. SQL keywords uppercase in examples; identifiers lowercase `snake_case`.

## The rule test

Applied to every line:

1. A tool decides it (`EXPLAIN` output, `squawk`, `plpgsql_check`, a failing test against a real PostgreSQL): name the command, and the squawk rule id where there is one. Do not restate the rule.
2. A model can ship the wrong form with a green run, and a primary source says so: state the rule and cite the source inline.
3. Otherwise: leave it out. No generic advice, and no second copy of a rule another skill owns; point to that skill instead.

Expert blogs (Use The Index, Luke; Cybertec; depesz; pganalyze) may explain *why*. The rule itself cites the manual, the release notes, the wiki or the tool's own documentation.

## Adding a reference or a skill

1. Write the reference in the shape above, and link it from its `SKILL.md` routing table.
2. A new skill: add it to the router's two tables, `rules/pgsql-context.mdc`, the session-start banner, the `pgsql-reviewer` load step, `hooks/skill-nudge.sh` if an edit can be recognised by its text, README.md, AGENTS.md, docs/testing.md, and CHANGELOG.md. `scripts/validate.py` fails until the routing surface and the inventories name it.
3. Add at least one eval case under `evals/`: a `prompt.md` written the way a user would ask, without naming the skill, plus three graders (an `llm` grader with concrete PASS and FAIL conditions, a `tool_used` grader for the skill, and a `regex` grader over `trace` with `arm: with-only` for the reference).
4. Run the checks in [testing.md](testing.md#validation).

## Refreshing the standards baseline (source registry)

When asked to *refresh the skills against current PostgreSQL practice*, re-read these sources in this order and update the affected files. Do not refresh from memory, and do not add a rule without a citation. Everything the skills assert should be traceable to one of these.

**Tier 1: normative, always check first**

| Source | URL | What it settles |
|---|---|---|
| Release status | <https://www.postgresql.org/> and <https://www.postgresql.org/support/versioning/> | which major version is released (an RC is not a floor) and which are supported |
| Release notes, current and next major | <https://www.postgresql.org/docs/18/release-18.html>, <https://www.postgresql.org/docs/19/release-19.html> | new features, the "Migration to Version N" incompatibilities |
| PostgreSQL 18 manual | <https://www.postgresql.org/docs/18/index.html> | every rule's primary citation; each skill's `## Sources` lists its chapters |
| PostgreSQL wiki, "Don't Do This" | <https://wiki.postgresql.org/wiki/Don%27t_Do_This> | type and construct anti-patterns |

Each reference's `## Sources` lists the manual chapters it rests on; those pages are the per-rule registry. The jsonb skill leans on `datatype-json` and `functions-json`, indexing on chapter 11, performance on `using-explain`, `planner-stats` and the `runtime-config-*` pages, migrations on `explicit-locking` and `sql-altertable`.

**Tier 2: drivers, migration runners and test tooling**

| Source | URL | What it settles |
|---|---|---|
| pgx v5 | <https://pkg.go.dev/github.com/jackc/pgx/v5> (and `pgtype`, `pgxpool`, `pgconn`); source pinned to a tag, e.g. <https://github.com/jackc/pgx/blob/v5.11.0/doc.go> | Go placeholders, query exec modes and the statement cache, scanning, batches, `CopyFrom`, jsonb encoding, error types |
| pgerrcode | <https://pkg.go.dev/github.com/jackc/pgerrcode> | SQLSTATE constants for retries and error mapping |
| PHP PDO PostgreSQL driver | <https://www.php.net/manual/en/ref.pdo-pgsql.php>, <https://www.php.net/manual/en/class.pdo-pgsql.php>, <https://www.php.net/manual/en/pdo.prepare.php> | PHP binding, placeholders, the `??` escape, `Pdo\Pgsql` |
| goose, golang-migrate | <https://pressly.github.io/goose/documentation/annotations/>, <https://github.com/golang-migrate/migrate/blob/master/database/postgres/README.md> | how each runner wraps a migration in a transaction |
| testcontainers-go postgres module, pgTAP | <https://golang.testcontainers.org/modules/postgres/>, <https://pgtap.org/documentation.html> | testing against a real server |
| Use The Index, Luke (reasoning only) | <https://use-the-index-luke.com/no-offset> | why keyset beats `OFFSET` |

**Tier 3: the enforcing tools**

| Source | URL | What it settles |
|---|---|---|
| squawk rules, CLI and config keys, safe migrations, releases | <https://squawkhq.com/docs/rules>, <https://squawkhq.com/docs/cli>, <https://squawkhq.com/docs/safe_migrations>, <https://github.com/sbdchd/squawk/releases> | rule ids the skills name; `references/squawk.toml` keys |
| squawk GitHub Action | <https://github.com/sbdchd/squawk-action/blob/main/action.yml> | the CI snippet in `/pgsql-lint-setup` |
| plpgsql_check | <https://github.com/okbob/plpgsql_check> | PL/pgSQL static checks |
| Postgres Language Server | <https://pg-language-server.com/latest/getting_started/> | the optional editor linter `/pgsql-lint-setup` mentions |
| HypoPG | <https://hypopg.readthedocs.io/en/latest/usage.html> | what-if indexes |
| `pg_stat_statements`, `auto_explain` | <https://www.postgresql.org/docs/18/pgstatstatements.html>, <https://www.postgresql.org/docs/18/auto-explain.html> | diagnostics recipes |

**Revision record**: the sources as last read. A refresh diffs each against this first, so it reads what changed rather than everything, then updates the table. Rules marked "checked" in a reference were also run against the versions below.

| Source | Revision read | Checked |
|---|---|---|
| PostgreSQL release status | 18.6 current (2026-08-13); 19 RC 1 (2026-10-15) | 2026-10-27 |
| PostgreSQL 19 release notes | "as of 2026-10-09" snapshot | 2026-10-27 |
| PostgreSQL 18 manual | 18.6; examples run on a `postgres:18` (18.6) container | 2026-10-27 |
| pgx | v5.11.0 (run with Go 1.27.3) | 2026-10-27 |
| PHP PDO | PHP 8.4.27 with `pdo_pgsql` | 2026-10-27 |
| squawk | v2.70.0 (2026-10-15); squawk-action v2.2.0; default `pg_version` is 15, so the shipped config sets 18 | 2026-10-27 |
| plpgsql_check | README at v2.10.16 (PostgreSQL 14 to 20) | 2026-10-27 |
| goose / Postgres Language Server / pgTAP | goose v3.29.0 docs; Postgres Language Server v0.28.2; pgTAP 1.3.4 | 2026-10-27 |

**Procedure**

1. Confirm the current *released* major version. A release candidate is not a floor: its features go in `## Newer in PostgreSQL N (hints)` sections, labelled.
2. Read the newest release notes, including the migration section, and diff each skill against them. The usual miss is a feature that landed after a skill was written, or a behaviour change in the migration section.
3. For each reference, re-open the pages in its `## Sources`, confirm each rule still matches, and update the checked date.
4. Re-check squawk rule ids and configuration keys. Update `references/squawk.toml` and the `/pgsql-lint-setup` block together; the validator fails if they differ. Never hard-code a squawk version in a rule; record it in `## Sources`.
5. Read the pgx changelog for v5 releases since the last refresh, and the PHP manual pages for PDO changes.
6. When the floor moves, follow [versioning.md](versioning.md#moving-the-postgresql-floor).
7. Run `python3 scripts/validate.py --check-links`; fix every moved page in the same refresh.
8. Update the **Revision record** above, then record the refresh in CHANGELOG.md under `## [Unreleased]`.

## Dual-host parity

Skills (slash-command skills included) and agents are shared by both hosts. The **Cursor** manifest (`.cursor-plugin/plugin.json`) declares each component path; **Claude** discovers the default folders. Keep the two manifests' shared metadata identical (`scripts/validate.py` checks parity), and the Cursor hook commands **workspace-relative** (`bash hooks/session-start.sh`), never `${CLAUDE_PLUGIN_ROOT}`.

## Before committing

Run the checks in [testing.md](testing.md#validation), then test triggering locally. When adding or renaming a component, sync **AGENTS.md**, **README.md**, **docs/testing.md** and **CHANGELOG.md** in lockstep.
