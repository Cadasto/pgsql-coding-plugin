# Changelog

All notable changes to this project are documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/), and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

## [0.1.0] - 2026-10-27

### Added
- Skills: `pgsql-coding` router with the `versions.md` reference (what needs PostgreSQL 17, 18 or 19).
- Skills: `pgsql-query`, `pgsql-jsonb`, `pgsql-schema`, `pgsql-indexing`, `pgsql-performance` and `pgsql-migrations`, each with cited `references/`.
- Skills: `/pgsql-lint-setup` writes the reference `.squawk.toml`.
- Agents: `pgsql-reviewer`, a report-only SQL reviewer.
- Agents: `pgsql-plan-analyst`, a report-only analyst of a long `EXPLAIN` plan or a before-and-after pair.
- Skills: `pgsql-performance` ships `scripts/plan-summary.py`, a TEXT and JSON plan summariser.
- Scripts: `scripts/plan-summary-test.py` with real PostgreSQL 18.6 plans in `scripts/testdata/plans/`.
- Hooks: `session-start.sh`, `lint-on-save.sh` (squawk, opt-in through `.squawk.toml`) and `skill-nudge.sh`, wired for Claude Code and Cursor.
- Cursor rule: `rules/pgsql-context.mdc` for `**/*.sql`.
- References: `references/squawk.toml`.
- Evals: one case per focused skill under `evals/`.
- Scripts: `scripts/validate.py` (with `--selftest` and `--check-links`), `scripts/validate.sh`, `scripts/hooks-test.sh`.
- Docs: `docs/install.md`, `docs/testing.md`, `docs/versioning.md`, `docs/authoring.md`; CI workflows `validate.yml` and `links.yml`.
