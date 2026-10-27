# Installing the PostgreSQL Coding Plugin

This page is for anyone installing, updating, or dogfooding the plugin: the Claude Code marketplace install, a local working copy for development, Cursor, and the tools the hooks and skills use on the host. The plugin is distributed for both [Claude Code](https://docs.claude.com/en/docs/claude-code/plugins) (`.claude-plugin/`) and [Cursor](https://cursor.com/docs/plugins) (`.cursor-plugin/`). Both hosts share the skill, agent, reference and hook-script content; only the manifests, the hook configs, and the Cursor-only rule in `rules/` differ. There is no build step and **no MCP server** to wire up.

## Claude Code

### Install (from the Cadasto marketplace)

```text
/plugin marketplace add Cadasto/plugin-marketplace
/plugin install pgsql-coding@cadasto
```

The marketplace name is `cadasto`, so the plugin is addressed as `pgsql-coding@cadasto`. It installs from the marketplace only once it has an entry there; see [versioning.md](versioning.md#marketplace).

### Load a local working copy (for development)

```bash
claude --plugin-dir /path/to/pgsql-coding-plugin
```

`--plugin-dir` loads the plugin from disk for **that session only**, which makes it the right tool for dogfooding an unreleased working copy. It is repeatable, so `--plugin-dir /path/to/go-coding-plugin --plugin-dir /path/to/pgsql-coding-plugin` loads both.

### Inspect / update

```bash
claude plugin validate .              # manifest + component structure
claude plugin details pgsql-coding    # component inventory + projected token cost
```

```text
/plugin marketplace update cadasto
/plugin update pgsql-coding
```

Restart the session for an update to take effect.

## Cursor

Add this repository as a plugin (Cursor **Settings → Plugins**, via Git URL or local path). The repo root contains `.cursor-plugin/plugin.json`, which declares the `skills`, `agents`, `rules`, and `hooks` paths. After changing content locally, reload or reinstall the plugin so Cursor picks it up.

## Host toolchain

Installing the plugin needs none of these. They are what the hooks call and what the skills ask for as evidence:

| Tool | Used for | If missing |
|------|----------|------------|
| **Python 3.9+** | `plan-summary.py` in `pgsql-performance`, run by `pgsql-plan-analyst` | the agent reads the plan by hand |
| **squawk** | `lint-on-save.sh` (when the project has a `.squawk.toml`), `/pgsql-lint-setup`, `pgsql-migrations`, `pgsql-reviewer` | the hook is a silent no-op; migration rules stay advice |
| **`psql`** (PostgreSQL 18 client) | running `EXPLAIN`, catalog queries and statistics queries against a database the user names | the skills reason from schema files and mark plan claims unconfirmed |
| **A PostgreSQL 18 test database** (for example the `postgres:18` container image) | tests against a real server, plans on realistic data | no evidence for index and rewrite decisions |
| **`pg_stat_statements`**, **`auto_explain`** | workload diagnosis in `pgsql-performance`; both ship with PostgreSQL and are enabled through `shared_preload_libraries` | per-statement `EXPLAIN` only |
| **`plpgsql_check`** extension | static checks of PL/pgSQL functions (`pgsql-schema`) | errors surface only when a function runs |
| **HypoPG** extension (optional) | what-if indexes without building them (`pgsql-indexing`) | build the index on a copy instead |

Install squawk with `npm install -g squawk-cli`, `pip install squawk-cli`, or a binary from its [releases page](https://github.com/sbdchd/squawk/releases) ([squawk quick start](https://squawkhq.com/docs/)); `squawk --version` confirms it is on `PATH`. Pin an exact squawk version in CI, as `/pgsql-lint-setup` describes. Install `plpgsql_check` and HypoPG into the development or CI database, not the host; their READMEs list the packages per platform.

### Permissions

Subagents, `pgsql-reviewer` included, run under the session's permission rules. To spare a prompt for the read-only linter, allow `Bash(squawk *)` in your Claude Code settings. Do **not** pre-approve `psql`: it can write, and the skills ask before they touch a database.

### PostgreSQL MCP servers

The plugin ships no MCP server. When one is connected (for example Postgres MCP Pro, with its explain and hypothetical-index tools), the skills use it under the same rule as `psql`: only against a database the user names, never production without explicit consent.

## Hooks

The plugin ships three host-agnostic hooks (Claude `hooks/hooks.json`, Cursor `hooks/cursor-hooks.json`). All three always exit 0 and never block an edit.

- **`session-start.sh`**: on session start, detects PostgreSQL use (pgx or lib/pq in `go.mod`, `ext-pdo_pgsql` or `ext-pgsql` in `composer.json`, a postgres, PostGIS or TimescaleDB image in a compose file, or a `*.sql` file within four directory levels) and prints one standards line. It suggests `/pgsql-lint-setup` when the repository has no `.squawk.toml`. Under Cursor, which runs a plugin hook from the plugin's install directory, it inspects `CURSOR_PROJECT_DIR` and prints the line as JSON `additional_context`.
- **`lint-on-save.sh`**: after each edit of a `*.sql` file (Claude `PostToolUse` on `Write`/`Edit`; Cursor `postToolUse` on `Write`), runs `squawk --reporter gcc` on that file, from the directory of the nearest `.squawk.toml` above it, so the project's settings apply. It runs only when squawk is on `PATH` **and** such a config exists: squawk's rules target migrations, so the project opts in. Up to 20 findings reach the model as `hookSpecificOutput.additionalContext` under Claude Code and as `additional_context` under Cursor.
- **`skill-nudge.sh`**: after each edit of a `.sql`, `.go` or `.php` file, names the one focused skill the added text calls for (a migration path or `ALTER TABLE` → `pgsql-migrations`; jsonb operators or SQL/JSON functions → `pgsql-jsonb`; `CREATE INDEX` → `pgsql-indexing`; `EXPLAIN` or `pg_stat_statements` → `pgsql-performance`; `CREATE TABLE`, functions, triggers, policies → `pgsql-schema`; other statements, pgx calls or PDO calls → `pgsql-query`), once per skill per session. The added text is Claude Code's `new_string` or `content`; Cursor documents no input fields for its `Write` tool, so there the hook matches the whole file. The session is Claude Code's `session_id` or Cursor's `conversation_id`. Go and PHP edits nudge only on unmistakable SQL, so ordinary host-language edits stay with go-coding and php-coding.

> The Cursor wiring follows [Cursor hooks](https://cursor.com/docs/agent/hooks): `postToolUse` with matcher `Write`, whose `additional_context` is "injected into the conversation after the tool result", rather than `afterFileEdit`, for which Cursor documents no output. Cursor does not document the `Write` tool's input fields, so the scripts read `file_path` or `path`; the Cursor checks in [testing.md](testing.md#local-triggering-tests) confirm it on a real install. If your Cursor version names the edit tool or its path field differently, adjust the matcher in `hooks/cursor-hooks.json` and the extraction in the scripts.
