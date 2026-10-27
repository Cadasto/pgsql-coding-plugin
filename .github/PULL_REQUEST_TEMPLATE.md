## Summary

<!-- What does this PR change, and why? -->

## Checklist

- [ ] `./scripts/validate.sh`, `python3 scripts/validate.py --selftest` and `./scripts/hooks-test.sh` pass
- [ ] `claude plugin validate .` passes
- [ ] Skill / command / agent triggering tested locally (see [docs/testing.md](../docs/testing.md))
- [ ] Cursor install tested locally when manifest, rule, or hook content changed (see [docs/install.md](../docs/install.md#cursor))
- [ ] Both manifests kept in sync when metadata changed: `.claude-plugin/plugin.json` and `.cursor-plugin/plugin.json`
- [ ] Every new or changed rule cites a source read for this change, and the reference's `## Sources` carries the checked date
- [ ] `python3 scripts/validate.py --check-links` passes when citations changed
- [ ] Version bumped and [CHANGELOG.md](../CHANGELOG.md) updated (if component content changed); see [docs/versioning.md](../docs/versioning.md)
- [ ] Docs synced (AGENTS.md, README.md, docs/testing.md, the router, the Cursor rule, `hooks/session-start.sh`) when components were added or renamed
