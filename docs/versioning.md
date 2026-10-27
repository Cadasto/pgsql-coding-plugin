# Versioning and releases

This page is for maintainers cutting a release: how to choose the version bump, the release steps, and how a release reaches users through the Cadasto marketplace. The plugin uses [Semantic Versioning](https://semver.org), adapted to skill, agent, and rule content:

| Bump | When |
|------|------|
| **Major** | A skill (slash commands included), agent, rule or hook is removed or renamed, or its behaviour or scope changes incompatibly |
| **Minor** | A new component is added, an existing one's coverage meaningfully expands, or the PostgreSQL floor moves |
| **Patch** | Typos, clarifications, source or citation fixes; no behaviour change |

While on the `0.x` line, treat the plugin as pre-stable: a breaking change may still ship in a minor bump.

## Release steps

1. Bump `version` in **both** manifests (they must agree): `.claude-plugin/plugin.json` and `.cursor-plugin/plugin.json`. Keep `description`, `author`, `license`, `repository` and `keywords` identical across both; `scripts/validate.py` enforces this parity.
2. Run `./scripts/validate.sh`, `python3 scripts/validate.py --selftest`, `./scripts/hooks-test.sh`, `python3 scripts/validate.py --check-links`, and `claude plugin validate .`.
3. **Dogfood:** load the working copy (`claude --plugin-dir /path/to/pgsql-coding`) and exercise the components against a real SQL change on **both** hosts; see [testing.md](testing.md).
4. Fold the accumulated `## [Unreleased]` notes into a dated `## [X.Y.Z] - YYYY-MM-DD` section in [CHANGELOG.md](../CHANGELOG.md) (Keep a Changelog groups in order: Added, Changed, Deprecated, Removed, Fixed, Security; see [AGENTS.md](../AGENTS.md#changelog-style)).
5. Sync the docs surface (AGENTS.md, README.md, docs/testing.md) with what shipped, and the component list in the session-start banner (`hooks/session-start.sh`).
6. Update the version badge in [README.md](../README.md) to `X.Y.Z`.
7. Commit (`chore(release): vX.Y.Z`) and tag: `git tag -a vX.Y.Z -m "pgsql-coding vX.Y.Z"`.
8. Push commits and the tag: `git push origin main --follow-tags`.
9. **Update the marketplace entry**: the release is not live until this lands. See below.

## Moving the PostgreSQL floor

The floor (PostgreSQL 18 today) is stated in the router, the Cursor rule, the session-start banner, the agent, every skill's version notes, AGENTS.md and README.md. When PostgreSQL 19 is released and the floor moves, follow the refresh procedure in [authoring.md](authoring.md#refreshing-the-standards-baseline): promote each `## Newer in PostgreSQL 19 (hints)` section into the rules, move the 18 table in the router's `versions.md` to provenance, and bump **minor**.

## No MCP coupling

This plugin has **no companion MCP server**, so there is no server-compatibility version to align.

## Marketplace

To be listed, the plugin needs an entry in the [Cadasto marketplace](https://github.com/Cadasto/plugin-marketplace) as `pgsql-coding@cadasto`. The catalog **pins every entry to a release tag**, so tagging and pushing a release here does not ship it: users see nothing until the marketplace entry moves.

After step 8, update the entry in `Cadasto/plugin-marketplace`:

1. Bump that entry's `version` to `X.Y.Z` and `source.ref` to `vX.Y.Z` together (validation there rejects a mismatch).
2. Bump the catalog's own `metadata.version`: a plugin minor or major is a catalog **minor**, a plugin patch is a catalog **patch**.
3. Add a dated `## [X.Y.Z] - YYYY-MM-DD` section in the catalog `CHANGELOG.md`, then run `python3 scripts/validate.py --fix`.

See the catalog's [docs/versioning.md](https://github.com/Cadasto/plugin-marketplace/blob/main/docs/versioning.md).

The catalog copies `description`, `version`, and `keywords` verbatim from `.claude-plugin/plugin.json`, so update the entry whenever any of those change, not only on a release.
