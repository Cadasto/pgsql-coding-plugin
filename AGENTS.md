# AI Guidelines: PostgreSQL Coding Plugin

This file provides guidance to AI coding assistants (Claude Code, Cursor, and compatible tools that read `AGENTS.md`) working in this repository. It is the **canonical** instruction set; `.claude/CLAUDE.md` imports it with `@../AGENTS.md`, and `.github/copilot-instructions.md` defers to it.

## Project Overview

The **PostgreSQL Coding Plugin** (`pgsql-coding`) is an AI plugin by Cadasto B.V. that teaches AI coding assistants **PostgreSQL coding standards**: writing and reviewing queries, `json` and `jsonb` with the SQL/JSON functions, schema design, indexing, performance analysis and debugging, and safe migrations. It targets **both Claude Code and Cursor** from a single shared component set. The human pitch is in [README.md](README.md); the shipped version is in the manifests and [CHANGELOG.md](CHANGELOG.md).

The plugin owns SQL, the schema, and the driver boundary (pgx v5 in Go, PDO in PHP). The host language belongs to the companion plugins `go-coding` and `php-coding`. Out of scope: other databases (MySQL, SQLite, SQL Server), ORMs' own query builders, and database administration beyond what an application developer needs to diagnose a slow query (replication, backups, server tuning). There is **no companion MCP server** and no `commands/` folder. Do not assume a file is present because it is documented here; check first.

Detail lives in `docs/`; keep a one-line rule here and point to the doc that owns it:

| Document | Owns |
|----------|------|
| [docs/install.md](docs/install.md) | Claude Code and Cursor install, local `--plugin-dir` loading, host toolchain, hooks |
| [docs/testing.md](docs/testing.md) | What each validator checks; the hook tests; the eval suite; the manual triggering tests |
| [docs/versioning.md](docs/versioning.md) | SemVer rules, release steps, moving the PostgreSQL floor, the marketplace repin |
| [docs/authoring.md](docs/authoring.md) | Component shapes, descriptions, the rule test, the standards source registry, dual-host parity |

## Domain Context

Guidance is grounded in sources read on 2026-10-27, not in memory:

- **Version floor: PostgreSQL 18.** The latest minor that day was 18.6 (2026-08-13). PG 18 forms are written flat, with no fallback for older servers; the router's `versions.md` reference lists what needs 17, 18 or 19. — <https://www.postgresql.org/docs/18/release-18.html>
- **PostgreSQL 19 is a release candidate** (RC 1, 2026-10-15; release notes "as of 2026-10-09"). Its additions appear only in `## Newer in PostgreSQL 19 (hints)` sections, never as rules, until it is released. — <https://www.postgresql.org/docs/19/release-19.html>
- **Primary sources**: the PostgreSQL 18 manual (<https://www.postgresql.org/docs/18/index.html>), the release notes, and the PostgreSQL wiki's "Don't Do This" (<https://wiki.postgresql.org/wiki/Don%27t_Do_This>). Driver rules cite pgx v5 (<https://pkg.go.dev/github.com/jackc/pgx/v5>) and the PHP manual (<https://www.php.net/manual/en/ref.pdo-pgsql.php>).
- **Enforcing tools**: `EXPLAIN (ANALYZE, BUFFERS)` for plans, `squawk` for migration safety (<https://squawkhq.com/docs/rules>), `plpgsql_check` for PL/pgSQL (<https://github.com/okbob/plpgsql_check>). A rule a tool decides is a command, not a paragraph.
- **Expert sources** (Use The Index, Luke; Cybertec; depesz; pganalyze) explain *why*; the rule itself cites a primary source.
- **Skill format** follows Anthropic's skill authoring best practices: an always-on description of at most 1,024 characters, a lean `SKILL.md`, and reference files one level deep, with a table of contents past 100 lines. — <https://platform.claude.com/docs/en/agents-and-tools/agent-skills/best-practices>

When a recommendation derives from a source, attribute it and distinguish cited rules from inference.

**Refreshing the skills against current PostgreSQL practice** (for example "check current PostgreSQL best practices and update the skills"): follow the source registry and procedure in [docs/authoring.md](docs/authoring.md#refreshing-the-standards-baseline-source-registry). Re-read the sources; never refresh from memory.

### Refreshing a dated fact

The version facts above are copied into the README, the router and its `versions.md`, the Cursor rule, the session-start banner, the agent, and every skill's PG 19 hints. When one changes, re-read the source, then list every copy:

```bash
grep -rnE 'PostgreSQL 1[89]|PG 1[89]|18\.[0-9]+|RC 1|2026-10-(09|15|27)|floor' --exclude-dir=.git --exclude-dir=evals --exclude=CHANGELOG.md .
```

Keep release numbers and "checked" dates in `## Sources` sections, `versions.md` and this file, not in rule text. Leave released CHANGELOG sections as they are.

## Repository Layout

Shared assets (skills, agents, hook scripts) are consumed by both hosts; host-specific manifests and hook configs are kept separate.

- **Claude manifest**: `.claude-plugin/plugin.json`: `name`, `version`, `description`, `author` (an **object** `{name, url}`; `claude plugin validate` rejects a string), `license`, `repository`, `keywords`. Claude Code discovers `skills/`, `agents/` and `hooks/` from the default folders.
- **Cursor manifest**: `.cursor-plugin/plugin.json`: the same metadata **plus** explicit path keys `skills`, `agents`, `rules`, `hooks`. No `mcpServers`.
- **Skills**: `skills/<name>/SKILL.md`, each focused skill with its `references/` folder (progressive disclosure: the description is always on, the body loads on use, a reference loads when the task needs it). `skills/pgsql-performance/scripts/plan-summary.py` is the stdlib-only plan summariser; its tests are `scripts/plan-summary-test.py` with real PostgreSQL 18.6 plans in `scripts/testdata/plans/`.
- **Agents**: `agents/pgsql-reviewer.md` (SQL review) and `agents/pgsql-plan-analyst.md` (`EXPLAIN` analysis).
- **Cursor rule**: `rules/pgsql-context.mdc` (`globs: ["**/*.sql"]`), mirroring the router.
- **Claude hooks**: `hooks/hooks.json` wires `session-start.sh` (`SessionStart`) and `lint-on-save.sh` + `skill-nudge.sh` (`PostToolUse`, `matcher: "Write|Edit"`), with `${CLAUDE_PLUGIN_ROOT}` paths.
- **Cursor hooks**: `hooks/cursor-hooks.json` wires the same scripts to `sessionStart` and `afterFileEdit` with **workspace-relative** commands.
- **Shared hook scripts** (host-agnostic; all exit 0 always):
  - `hooks/session-start.sh`: detects PostgreSQL use (pgx or lib/pq in `go.mod`, `ext-pdo_pgsql` in `composer.json`, a postgres image in a compose file, or a `*.sql` file) and prints one line naming the floor, the skills and the reviewer.
  - `hooks/lint-on-save.sh`: after a `*.sql` edit, runs `squawk --reporter gcc` on that file when squawk is on PATH and a `.squawk.toml` exists in the file's directory or a parent; findings reach the model as `hookSpecificOutput.additionalContext` (Claude Code) or plain lines (Cursor).
  - `hooks/skill-nudge.sh`: after a `.sql`, `.go` or `.php` edit, names ONE focused skill matching the text the edit adds, once per skill per session. Go and PHP edits nudge only on unmistakable SQL.
- **References**: top-level `references/squawk.toml`, the shipped squawk config; the `/pgsql-lint-setup` scaffold block must stay byte-identical to it.
- **Evals**: `evals/<case>/` with `prompt.md` and `graders/`, run by `claude plugin eval`. Results go to `evals/results/`, which is gitignored.
- **Scripts**: `scripts/validate.sh` (wraps the stdlib-only `scripts/validate.py`), `scripts/hooks-test.sh`, `scripts/plan-summary-test.py`.
- **CI**: `.github/workflows/validate.yml` (validator, `--selftest`, hook tests, plan-summary tests) and `.github/workflows/links.yml` (link check). `.github/` also holds issue and PR templates and `copilot-instructions.md`.
- **Contributor docs**: `docs/install.md`, `testing.md`, `versioning.md`, `authoring.md`. Planning and research notes live under `docs/plans/` and `docs/research/`, **gitignored**.

## Components

| Kind | Shipped |
|------|---------|
| Skills | `pgsql-coding` (auto-invoked router, with `versions.md`) + the focused, load-on-use `pgsql-query`, `pgsql-jsonb`, `pgsql-schema`, `pgsql-indexing`, `pgsql-performance`, `pgsql-migrations`, each with its `references/` |
| Slash command (user-invoked skill) | `/pgsql-lint-setup` (write the reference `.squawk.toml`) |
| Agents | `pgsql-reviewer`: context-isolated, report-only reviewer of SQL in `.sql` files, migrations, and Go or PHP query strings. `pgsql-plan-analyst`: context-isolated, report-only analyst of a long `EXPLAIN` plan or a before-and-after pair; runs the plan summariser and reads only the flagged nodes. Both load the skills with the `Skill` tool, never edit, never run DML, dispatch no sub-agents, and use `tools:` not `allowed-tools:` |
| Cursor rule | `rules/pgsql-context.mdc`, scoped to `**/*.sql`, mirroring the router |
| Hooks | `session-start`, `lint-on-save`, `skill-nudge` (see Repository Layout) |

## Development

No build step; the plugin is Markdown, JSON and three shell hooks. Validate and dogfood locally:

```bash
./scripts/validate.sh                     # manifests, parity, frontmatter, references, routing surface, docs, evals
python3 scripts/validate.py --selftest    # proves each check still catches its failure case (CI runs it)
python3 scripts/validate.py --check-links # every cited URL resolves (needs the network)
./scripts/hooks-test.sh                   # bash tests for the three hooks
python3 scripts/plan-summary-test.py      # the plan summariser against real PostgreSQL 18 plans
claude plugin validate .                  # manifest + component structure (no extra deps)
claude --plugin-dir /path/to/pgsql-coding-plugin # load locally for one session (dogfooding)
```

What each check covers is in [docs/testing.md](docs/testing.md#validation).

### File Conventions

- Skills go in `skills/<name>/SKILL.md`, including the user-invoked `/pgsql-lint-setup` (with `argument-hint` and `allowed-tools`); a skill's topic files go in `skills/<name>/references/`. Agents go in `agents/<name>.md`. The legacy `commands/` layout is not used.
- All Markdown components use **YAML frontmatter**; reference files carry none. Use **kebab-case** for every directory and file name.
- Every reference ends with `## Sources`, each entry marked "(checked YYYY-MM-DD)".
- `allowed-tools:` (skills) pre-approves tools; **agents use `tools:` instead**.
- Use `${CLAUDE_PLUGIN_ROOT}` for intra-plugin paths in Claude hook commands; never hardcode absolute paths or `~`.
- Full authoring conventions, including the rule test: [docs/authoring.md](docs/authoring.md).

### Documentation Sync

When adding or renaming a component, update in lockstep: the router's two tables, `rules/pgsql-context.mdc`, the session-start banner, the `pgsql-reviewer` load step, **AGENTS.md**, **README.md**, **docs/testing.md**, and **CHANGELOG.md**; hooks also in **docs/install.md**. The validator fails if a shipped skill, agent or hook is missing from these.

### CHANGELOG style

- Entries accumulate under `## [Unreleased]` and fold into the next `## [X.Y.Z] - YYYY-MM-DD` section at release.
- Use the Keep a Changelog groups in order (**Added, Changed, Deprecated, Removed, Fixed, Security**), omitting empty groups.
- One terse line per bullet; lead with the subsystem (`Skills:`, `Agents:`, `Hooks:`, `Docs:`, `Cursor rule:`, `Scripts:`, `Evals:`) and use backticks for file, command, tool and key names. No rationale or PR links.

### Commit Messages

- Follow [Conventional Commits](https://www.conventionalcommits.org/en/v1.0.0/), e.g. `feat(skills): add pgsql-jsonb indexing reference`, `fix(hooks): escape squawk output`; the release commit is `chore(release): vX.Y.Z`.
- Scopes: `skills`, `agents`, `hooks`, `rules`, `evals`, `scripts`, `docs`.

### Versioning

- Keep `version` and the shared metadata **in sync across both** manifests; the validator enforces parity.
- Follow **Semantic Versioning**; update both manifests and **CHANGELOG.md** when releasing. Bump rules and release steps: [docs/versioning.md](docs/versioning.md).

### Branching

- Use feature branches and pull requests. CI (`validate.yml`) runs on every pull request and on pushes to `main`.

## Gotchas

- **Agents use `tools:`, not `allowed-tools:`.** In an agent file `allowed-tools:` is ignored and the agent silently inherits *all* tools. The validator flags it.
- **`EXPLAIN ANALYZE` executes the statement.** Every component that suggests running SQL says so, wraps DML in `BEGIN ... ROLLBACK`, and asks before touching any database the user did not name. Keep that wording when editing.
- **Keep the two manifests in parity.** Cursor needs explicit path keys; Claude relies on default-folder discovery.
- **The Cursor hook uses a workspace-relative command** (`bash hooks/session-start.sh`), *not* `${CLAUDE_PLUGIN_ROOT}` (a Claude-Code-only variable). Don't "fix" it.
- **Every hook script must be wired on both hosts**, exist, and be executable; the validator checks all three.
- **`lint-on-save` is opt-in by the project.** It runs only where a `.squawk.toml` exists; squawk's rules target migrations, so linting every `.sql` file in every repository would be noise.
- **The squawk config has two copies**: `references/squawk.toml` and the block in `/pgsql-lint-setup`. Change both; the validator compares them byte for byte.
- **The name says `pgsql`, not "Postgres".** "Postgres" and "PostgreSQL" are registered trademarks of the PostgreSQL Community Association of Canada, and their use in a product name needs its prior approval; descriptive use ("for PostgreSQL") does not. Do not rename the plugin without that approval. — <https://www.postgresql.org/about/policies/trademarks/>
- **Don't invent a companion MCP server.** A PostgreSQL MCP server the user connects (for example Postgres MCP Pro) is used when present, under the same consent rule as `psql`.
- **Register in the marketplace separately, and repin it on every release.** See [docs/versioning.md](docs/versioning.md#marketplace).
