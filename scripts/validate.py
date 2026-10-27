#!/usr/bin/env python3
"""Validate this plugin's manifests, components, references, hooks, docs and evals.

This is a single-plugin repository (the plugin lives at the repo root), supporting
both Claude Code (``.claude-plugin/plugin.json``) and Cursor (``.cursor-plugin/plugin.json``).
Checks:
  * both manifests parse as JSON and carry the required fields;
  * dual-host parity (name/version/description/author/license/repository/keywords agree);
  * every component path declared in a manifest exists inside the plugin dir;
  * kebab-case directory/file names for skills, references, agents, commands, and rules;
  * hook-config JSON validity, and dual-host hook parity: both configs present, the same
    ``hooks/*.sh`` wired for the equivalent event on both hosts, each wired script present and
    executable, none unwired; Claude commands through ``${CLAUDE_PLUGIN_ROOT}``, Cursor commands
    workspace-relative;
  * SKILL.md / agent / command frontmatter: required keys, ``name`` matching the directory or
    filename, descriptions within the Agent Skills limit (folded and literal blocks measured
    whole), no unquoted ``: `` or `` #``. Agents
    MUST declare ``tools:`` (never ``allowed-tools:``, which Claude Code silently ignores so the
    agent inherits *all* tools);
  * skill references (progressive disclosure): every ``references/*.md`` linked one level deep
    from its SKILL.md and every link resolving, no frontmatter, a ``## Contents`` list past 100
    lines, a hard ceiling on length, and a ``## Sources`` section in every one;
  * the routing surface: every focused skill named by the router, the Cursor rule, the
    session-start banner, and the reviewer agent;
  * doc component inventories: every shipped skill, agent and hook named in the docs that claim
    to list them (one-directional, so tombstones for removed components stay legal);
  * the tie-break sentence restated identically in the router, the Cursor rule and the agent;
  * the ``/pgsql-lint-setup`` toml block byte-identical to ``references/squawk.toml``;
  * eval cases: a ``prompt.md`` and graders with frontmatter, a skill-fired grader naming a
    shipped skill, and a read-reference grader naming a reference that exists.

This plugin has no MCP backend, so there is intentionally no ``.mcp.json`` check.

Dependency-free (stdlib only) so the ``scripts/validate.sh`` soft-skip is the *only*
reason it wouldn't run.

Usage:
    python3 scripts/validate.py                # verify this tree
    python3 scripts/validate.py --selftest     # verify the checks themselves still catch things
    python3 scripts/validate.py --check-links  # every URL cited in components and docs resolves (network)
"""
import http.server
import json
import os
import re
import sys
import tempfile
import threading
import time
import urllib.error
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
errors = []

PLUGIN_NAME_RE = re.compile(r"^[a-z0-9](?:[a-z0-9.-]*[a-z0-9])?$")
KEBAB_RE = re.compile(r"^[a-z0-9]+(?:-[a-z0-9]+)*$")
# Component-path fields a manifest may declare (Cursor lists them explicitly). No
# `mcpServers`: this plugin bundles no MCP server.
MANIFEST_PATH_FIELDS = ("logo", "rules", "skills", "agents", "commands", "hooks")
# Fields that must agree across the Claude and Cursor manifests.
SYNCED_FIELDS = ("name", "version", "description", "author", "license", "repository", "keywords")
# Agent Skills limits and conventions (platform.claude.com, "Skill authoring best practices").
DESCRIPTION_MAX = 1024
REFERENCE_TOC_THRESHOLD = 100  # a reference longer than this needs a "## Contents" section
REFERENCE_MAX_LINES = 200      # past this a reference should be split, not scrolled
SKILL_BODY_MAX_WORDS = 1500    # SKILL.md bodies stay lean; detail belongs in references/
REF_LINK_RE = re.compile(r"\]\(references/([a-z0-9-]+\.md)\)")
ROUTER = "pgsql-coding"
COMMAND_SKILLS = ("pgsql-lint-setup",)
REVIEWER = "agents/pgsql-reviewer.md"
CURSOR_RULE = "rules/pgsql-context.mdc"
BANNER = "hooks/session-start.sh"
# Hook events that mean the same thing on each host, so the same scripts must be wired for
# both. Claude event -> Cursor event.
EQUIVALENT_HOOK_EVENTS = {"SessionStart": "sessionStart", "PostToolUse": "afterFileEdit"}
# Docs that inventory the component surface, and which kinds each one claims to cover.
INVENTORY_DOCS = {
    "README.md": ("skills", "agents", "hooks"),
    "AGENTS.md": ("skills", "agents", "hooks"),
    "docs/testing.md": ("skills", "agents", "hooks"),
    "docs/install.md": ("hooks",),
}
# The tie-break order, restated (not linked) in three independent files. Checked verbatim after
# collapsing whitespace, since the sentence may hard-wrap differently in each file.
TIE_BREAK_SENTENCE = (
    "correct under NULLs and concurrent writes, then the measured plan on realistic data, then "
    "the form the PostgreSQL manual documents for that purpose, then the shorter statement"
)
TIE_BREAK_FILES = ("skills/pgsql-coding/SKILL.md", CURSOR_RULE, REVIEWER)
SQUAWK_REFERENCE = "references/squawk.toml"
SQUAWK_SCAFFOLD = "skills/pgsql-lint-setup/SKILL.md"


def err(msg):
    errors.append(msg)


def load_json(path: Path, label: str):
    try:
        return json.loads(path.read_text())
    except Exception as e:
        err(f"{path.relative_to(ROOT)}: cannot parse JSON ({label}): {e}")
        return None


def check_kebab(name: str, label: str):
    if not KEBAB_RE.match(name):
        err(f"{label}: name '{name}' is not kebab-case")


def frontmatter(text: str):
    m = re.match(r"\A---\n(.*?)\n---\n", text, re.DOTALL)
    return m.group(1) if m else None


def frontmatter_value(front: str, field: str):
    """A top-level frontmatter field's value as YAML reads it: a folded (`>`, `>-`) or literal
    (`|`) block, or a plain scalar continued on indented lines, joined into one string, quotes
    removed. None when the field is absent. Enough to measure a description, not a YAML parser."""
    lines = front.splitlines()
    for i, line in enumerate(lines):
        m = re.match(rf"^{field}:[ \t]*(.*)$", line)
        if not m:
            continue
        head, cont = m.group(1).strip(), []
        for nxt in lines[i + 1:]:
            if nxt.strip() and not nxt[:1].isspace():
                break
            cont.append(nxt.strip())
        if head[:1] == "|":
            return "\n".join(cont).strip()
        value = " ".join(c for c in ([] if head[:1] == ">" else [head]) + cont if c)
        if len(value) > 1 and value[0] in "\"'" and value[-1] == value[0]:
            value = value[1:-1]
        return value
    return None


def check_frontmatter_scalars(front: str, rel: str):
    """Stdlib-only guard for the most common frontmatter YAML breakage: an unquoted scalar
    value containing a ': ' (colon-space) or ' #', which a real YAML parser reads as a nested
    mapping or a comment, so at runtime the component loads with EMPTY metadata (every field
    silently dropped). This is NOT a full YAML parser (`claude plugin validate` does that); it
    exists because CI runs only this Python validator, so this class of error must fail here too."""
    for line in front.splitlines():
        m = re.match(r"^([A-Za-z0-9_-]+):\s(.+)$", line)
        if not m:
            continue
        value = m.group(2).strip()
        if value[:1] in ('"', "'", "[", "{", "|", ">", "&", "*", "#"):
            continue  # quoted or structured: trust the author / real parser
        if ": " in value:
            err(f"{rel}: frontmatter '{m.group(1)}' has an unquoted ': ' in its value; "
                f"quote the value or YAML parses it as a nested mapping (metadata silently dropped)")
        if " #" in value:
            err(f"{rel}: frontmatter '{m.group(1)}' has an unquoted ' #' in its value; quote the value")


def skill_names():
    skills_dir = ROOT / "skills"
    if not skills_dir.is_dir():
        return []
    return [d.name for d in sorted(skills_dir.iterdir()) if (d / "SKILL.md").is_file()]


def validate_skills():
    skills_dir = ROOT / "skills"
    if not skills_dir.is_dir():
        return
    for skill_dir in sorted(d for d in skills_dir.iterdir() if d.is_dir()):
        check_kebab(skill_dir.name, f"skills/{skill_dir.name}")
        skill_md = skill_dir / "SKILL.md"
        rel = skill_md.relative_to(ROOT)
        if not skill_md.is_file():
            err(f"{rel}: missing SKILL.md")
            continue
        text = skill_md.read_text()
        front = frontmatter(text)
        if front is None:
            err(f"{rel}: missing YAML frontmatter")
            continue
        check_frontmatter_scalars(front, str(rel))
        for field in ("name", "description"):
            if not re.search(rf"^{field}:", front, re.MULTILINE):
                err(f"{rel}: frontmatter missing '{field}'")
        fm_name = re.search(r"^name:\s*(\S+)", front, re.MULTILINE)
        if fm_name and fm_name.group(1) != skill_dir.name:
            err(f"{rel}: frontmatter name '{fm_name.group(1)}' != directory '{skill_dir.name}'")
        fm_desc = frontmatter_value(front, "description")
        if fm_desc and len(fm_desc) > DESCRIPTION_MAX:
            err(f"{rel}: description is {len(fm_desc)} characters; the Agent Skills limit is {DESCRIPTION_MAX}")
        body = text[re.match(r"\A---\n.*?\n---\n", text, re.DOTALL).end():]
        words = len(body.split())
        if words > SKILL_BODY_MAX_WORDS:
            err(f"{rel}: body is {words} words; keep it under {SKILL_BODY_MAX_WORDS} "
                f"and move detail into references/")
        validate_skill_references(skill_dir, text)


def validate_skill_references(skill_dir: Path, body: str):
    """A skill's references/ files must be reachable one level deep: every file is linked from
    SKILL.md, every link resolves, a file past the TOC threshold opens with a Contents list, and
    every file ends with the sources a refresh re-reads."""
    ref_dir = skill_dir / "references"
    linked = set(REF_LINK_RE.findall(body))
    present = {f.name for f in ref_dir.glob("*.md")} if ref_dir.is_dir() else set()
    rel = (skill_dir / "SKILL.md").relative_to(ROOT)
    for name in sorted(linked - present):
        err(f"{rel}: links references/{name}, which does not exist")
    for name in sorted(present - linked):
        err(f"{skill_dir.relative_to(ROOT)}/references/{name}: not linked from SKILL.md")
    for name in sorted(present):
        label = f"{skill_dir.relative_to(ROOT)}/references/{name}"
        check_kebab(name[:-3], label)
        text = (ref_dir / name).read_text()
        lines = len(text.splitlines())
        if text.startswith("---\n"):
            err(f"{label}: reference files carry no frontmatter")
        if lines > REFERENCE_TOC_THRESHOLD and not re.search(r"^## Contents", text, re.MULTILINE):
            err(f"{label}: longer than {REFERENCE_TOC_THRESHOLD} lines without a '## Contents' section")
        if lines > REFERENCE_MAX_LINES:
            err(f"{label}: {lines} lines; split it (limit {REFERENCE_MAX_LINES})")
        if not re.search(r"^## Sources", text, re.MULTILINE):
            err(f"{label}: no '## Sources' section; every rule needs its citations")


def validate_md_components(subdir: str, *, require_name: bool, is_agent: bool = False):
    """Validate flat .md components (agents/, commands/): kebab-case filename, frontmatter
    present with the required fields, and any `name` matching the filename stem. Agents are
    additionally checked for the `allowed-tools:` foot-gun."""
    comp_dir = ROOT / subdir
    if not comp_dir.is_dir():
        return
    for md in sorted(comp_dir.glob("*.md")):
        rel = md.relative_to(ROOT)
        check_kebab(md.stem, str(rel))
        front = frontmatter(md.read_text())
        if front is None:
            err(f"{rel}: missing YAML frontmatter")
            continue
        check_frontmatter_scalars(front, str(rel))
        for field in (("name", "description") if require_name else ("description",)):
            if not re.search(rf"^{field}:", front, re.MULTILINE):
                err(f"{rel}: frontmatter missing '{field}'")
        fm_name = re.search(r"^name:\s*(\S+)", front, re.MULTILINE)
        if fm_name and fm_name.group(1) != md.stem:
            err(f"{rel}: frontmatter name '{fm_name.group(1)}' != filename '{md.stem}'")
        if is_agent and re.search(r"^allowed-tools:", front, re.MULTILINE):
            err(f"{rel}: agents must declare 'tools:' not 'allowed-tools:' "
                f"('allowed-tools:' is silently ignored, so the agent inherits ALL tools)")
        if is_agent and not re.search(r"^tools:", front, re.MULTILINE):
            err(f"{rel}: agents must declare 'tools:' (without it the agent inherits ALL tools)")


def validate_rules():
    """Cursor rule files (rules/*.mdc): kebab-case filename plus a `description` in frontmatter."""
    rules_dir = ROOT / "rules"
    if not rules_dir.is_dir():
        return
    for rule in sorted(rules_dir.glob("*.mdc")):
        rel = rule.relative_to(ROOT)
        check_kebab(rule.stem, str(rel))
        front = frontmatter(rule.read_text())
        if front is None:
            err(f"{rel}: missing YAML frontmatter")
            continue
        check_frontmatter_scalars(front, str(rel))
        if not re.search(r"^description:", front, re.MULTILINE):
            err(f"{rel}: frontmatter missing 'description'")


def mentions(body: str, name: str) -> bool:
    # Bounded so a shorter name is not satisfied by a longer one that contains it.
    return re.search(rf"(?<![\w-]){re.escape(name)}(?![\w-])", body) is not None


def validate_routing_surface():
    """The router, the Cursor rule, the session-start banner and the reviewer each route to the
    focused skills. A skill added to skills/ but missing from one of them is never loaded on
    that path, and nothing else would notice."""
    focused = [s for s in skill_names() if s != ROUTER and s not in COMMAND_SKILLS]
    surfaces = {
        f"skills/{ROUTER}/SKILL.md": focused + list(COMMAND_SKILLS),
        CURSOR_RULE: focused + list(COMMAND_SKILLS),
        BANNER: focused,
        REVIEWER: focused,
    }
    for rel, required in surfaces.items():
        path = ROOT / rel
        if not path.is_file():
            err(f"{rel}: missing; it must route to every focused skill")
            continue
        body = path.read_text()
        for name in required:
            if not mentions(body, name):
                err(f"{rel}: does not name the skill '{name}'; it is unreachable from there")


def validate_manifest_paths(manifest: dict, label: str):
    for field in MANIFEST_PATH_FIELDS:
        value = manifest.get(field)
        if value is None:
            continue
        paths = [value] if isinstance(value, str) else value if isinstance(value, list) else []
        for path_value in paths:
            if not isinstance(path_value, str) or path_value.startswith(("http://", "https://")):
                continue
            resolved = (ROOT / path_value).resolve()
            try:
                resolved.relative_to(ROOT.resolve())
            except ValueError:
                err(f"{label}: {field} path '{path_value}' escapes the plugin directory")
                continue
            if not resolved.exists():
                err(f"{label}: {field} references missing path '{path_value}'")


def validate_json_file(path: Path, label: str):
    if path.is_file():
        load_json(path, label)


def _hook_commands(config: dict) -> dict:
    """Map each event name in a hook config to the `command` strings under it. Both host
    schemas nest differently (Claude groups by matcher, Cursor does not), so walk whatever is
    under the event and collect every `command` string found."""
    found = {}
    for event, entries in (config.get("hooks") or {}).items():
        commands, stack = [], [entries]
        while stack:
            node = stack.pop()
            if isinstance(node, dict):
                if isinstance(node.get("command"), str):
                    commands.append(node["command"])
                stack.extend(node.values())
            elif isinstance(node, list):
                stack.extend(node)
        found[event] = commands
    return found


def _hook_scripts(config: dict) -> dict:
    """Map each event name in a hook config to the set of `hooks/*.sh` scripts it wires."""
    return {event: {s for cmd in cmds for s in re.findall(r"hooks/([A-Za-z0-9._-]+\.sh)", cmd)}
            for event, cmds in _hook_commands(config).items()}


def validate_hook_parity():
    """Dual-host hook parity: the same scripts must be wired for the equivalent event on both
    hosts, every wired script must exist and be executable, and no `hooks/*.sh` may sit in the
    tree unwired. Claude Code commands reach their script through `${CLAUDE_PLUGIN_ROOT}`; Cursor
    does not set it, so Cursor commands stay workspace-relative."""
    claude_path, cursor_path = ROOT / "hooks" / "hooks.json", ROOT / "hooks" / "cursor-hooks.json"
    configs = [p for p in (claude_path, cursor_path) if p.is_file()]
    if not configs and not list((ROOT / "hooks").glob("*.sh")):
        return  # a plugin without hooks
    for path in (claude_path, cursor_path):
        if not path.is_file():
            err(f"hooks/{path.name}: missing; every hook is wired for both hosts (dual-host parity)")
    if len(configs) < 2:
        return
    claude, cursor = load_json(claude_path, "Claude hooks"), load_json(cursor_path, "Cursor hooks")
    if claude is None or cursor is None:
        return
    for event, commands in _hook_commands(claude).items():
        for cmd in commands:
            if "hooks/" in cmd and "${CLAUDE_PLUGIN_ROOT}/hooks/" not in cmd:
                err(f"hooks/hooks.json: {event} command '{cmd}' must reach its script through ${{CLAUDE_PLUGIN_ROOT}}")
    for event, commands in _hook_commands(cursor).items():
        for cmd in commands:
            if "CLAUDE_PLUGIN_ROOT" in cmd:
                err(f"hooks/cursor-hooks.json: {event} command '{cmd}' uses CLAUDE_PLUGIN_ROOT, which Cursor "
                    f"does not set; keep the path workspace-relative")
    claude_events, cursor_events = _hook_scripts(claude), _hook_scripts(cursor)
    wired = set()
    for claude_event, cursor_event in EQUIVALENT_HOOK_EVENTS.items():
        here, there = claude_events.get(claude_event, set()), cursor_events.get(cursor_event, set())
        wired |= here | there
        for name in sorted(here - there):
            err(f"hooks/cursor-hooks.json: '{name}' is wired for Claude's {claude_event} but "
                f"not for Cursor's {cursor_event} (dual-host parity)")
        for name in sorted(there - here):
            err(f"hooks/hooks.json: '{name}' is wired for Cursor's {cursor_event} but not for "
                f"Claude's {claude_event} (dual-host parity)")
    for event in set(claude_events) - set(EQUIVALENT_HOOK_EVENTS):
        wired |= claude_events[event]
    for event in set(cursor_events) - set(EQUIVALENT_HOOK_EVENTS.values()):
        wired |= cursor_events[event]
    for name in sorted(wired):
        script = ROOT / "hooks" / name
        if not script.is_file():
            err(f"hooks: wired script 'hooks/{name}' does not exist")
        elif not os.access(script, os.X_OK):
            err(f"hooks/{name}: wired but not executable (chmod +x)")
    for script in sorted((ROOT / "hooks").glob("*.sh")):
        if script.name not in wired:
            err(f"hooks/{script.name}: present in the tree but wired by neither host's hook config")


def validate_doc_inventories():
    """Every shipped component must appear in the docs that claim to inventory the surface.
    One-directional on purpose: it proves each component IS documented, not that every name
    mentioned still exists, so deliberate tombstones and cross-references stay legal."""
    kinds = {
        "skills": skill_names(),
        "agents": [m.stem for m in sorted((ROOT / "agents").glob("*.md"))],
        "hooks": [s.stem for s in sorted((ROOT / "hooks").glob("*.sh"))],
    }
    for doc_name, covered in INVENTORY_DOCS.items():
        doc = ROOT / doc_name
        if not doc.is_file():
            continue
        body = doc.read_text()
        for kind in covered:
            for component in kinds[kind]:
                if not mentions(body, component):
                    err(f"{doc_name}: does not mention the shipped {kind[:-1]} '{component}'; "
                        f"its component inventory is stale")


def validate_tie_break_parity():
    """The tie-break order is restated, not linked, in three independent files, so an edit to
    one silently leaves the others stating a different order. Collapse whitespace runs and
    require TIE_BREAK_SENTENCE verbatim."""
    for rel in TIE_BREAK_FILES:
        path = ROOT / rel
        if not path.is_file():
            err(f"{rel}: missing; cannot verify the tie-break sentence")
            continue
        collapsed = re.sub(r"\s+", " ", path.read_text())
        if TIE_BREAK_SENTENCE not in collapsed:
            err(f"{rel}: does not carry the tie-break sentence verbatim; "
                f"expected '{TIE_BREAK_SENTENCE}'")


def validate_squawk_scaffold():
    """Advice == tooling: the toml block /pgsql-lint-setup writes must be the shipped reference
    config, byte for byte, so the two copies cannot drift."""
    ref, skill = ROOT / SQUAWK_REFERENCE, ROOT / SQUAWK_SCAFFOLD
    if not (ref.is_file() and skill.is_file()):
        if ref.is_file() != skill.is_file():
            err(f"{SQUAWK_REFERENCE} and {SQUAWK_SCAFFOLD} must ship together")
        return
    blocks = re.findall(r"```toml\n(.*?)```", skill.read_text(), re.DOTALL)
    if len(blocks) != 1:
        err(f"{SQUAWK_SCAFFOLD}: expected exactly one ```toml block (the scaffold), found {len(blocks)}")
        return
    if blocks[0] != ref.read_text():
        err(f"{SQUAWK_SCAFFOLD}: the toml scaffold block differs from {SQUAWK_REFERENCE}; keep them identical")


def validate_evals():
    """Each eval case has a prompt and graders with frontmatter; a skill-fired grader names a
    shipped skill; a read-reference grader names a reference file that exists."""
    evals_dir = ROOT / "evals"
    if not evals_dir.is_dir():
        return
    skills = set(skill_names())
    agents = {m.stem for m in (ROOT / "agents").glob("*.md")}
    references = {p.name for p in (ROOT / "skills").glob("*/references/*.md")}
    for case in sorted(d for d in evals_dir.iterdir() if d.is_dir() and d.name != "results"):
        label = f"evals/{case.name}"
        check_kebab(case.name, label)
        prompt = case / "prompt.md"
        if not prompt.is_file() or frontmatter(prompt.read_text()) is None:
            err(f"{label}: needs a prompt.md with frontmatter")
        graders = sorted((case / "graders").glob("*.md")) if (case / "graders").is_dir() else []
        if not graders:
            err(f"{label}: has no graders/")
        for grader in graders:
            text = grader.read_text()
            front = frontmatter(text)
            if front is None or not re.search(r"^type:", front, re.MULTILINE):
                err(f"{label}/graders/{grader.name}: needs frontmatter with a 'type'")
                continue
            # A tool_used grader names a skill (`tool: Skill`) or an agent (`tool: Agent`) by its
            # unqualified name after an optional `plugin:` prefix.
            tool = re.search(r"^tool:\s*(\S+)", front, re.MULTILINE)
            shipped, kind = (agents, "agent") if tool and tool.group(1) == "Agent" else (skills, "skill")
            for name in re.findall(r'\(\?:\[\\w-\]\+:\)\?([a-z0-9-]+)"', front):
                if name not in shipped:
                    err(f"{label}/graders/{grader.name}: expects {kind} '{name}', which does not ship")
            # A grader names one reference or an alternation of them, optionally under its skill:
            # `pgsql-jsonb/references/indexing\.md`, `references/(design|types)\.md`.
            for skill, group, single in re.findall(
                    r"(?:([a-z0-9-]+)/)?references/(?:\(([a-z0-9|-]+)\)|([a-z0-9-]+))\\?\.md", front):
                for ref in (group.split("|") if group else [single]):
                    if skill and skill in skills:
                        exists = (ROOT / "skills" / skill / "references" / f"{ref}.md").is_file()
                    else:
                        exists = f"{ref}.md" in references
                    if not exists:
                        where = f"skills/{skill}/references/" if skill in skills else "any skill's references/"
                        err(f"{label}/graders/{grader.name}: expects '{ref}.md' in {where}, which does not exist")


def main():
    manifests = {}
    for subdir, label in ((".claude-plugin", "Claude manifest"), (".cursor-plugin", "Cursor manifest")):
        manifest_path = ROOT / subdir / "plugin.json"
        if not manifest_path.is_file():
            err(f"missing {manifest_path.relative_to(ROOT)}")
            continue
        data = load_json(manifest_path, label)
        if data is None:
            continue
        manifests[subdir] = data
        name = data.get("name")
        if not name or not PLUGIN_NAME_RE.match(name):
            err(f"{label}: 'name' must be lowercase alphanumerics, hyphens, and periods")
        for field in ("name", "version", "description"):
            if not data.get(field):
                err(f"{label}: required field '{field}' is missing or empty")
        if not isinstance(data.get("author"), dict):
            err(f"{label}: 'author' must be an object {{name, url}}; `claude plugin validate` rejects a string")
        validate_manifest_paths(data, label)

    if len(manifests) == 2:
        claude, cursor = manifests[".claude-plugin"], manifests[".cursor-plugin"]
        for field in SYNCED_FIELDS:
            if claude.get(field) != cursor.get(field):
                err(f"manifests disagree on '{field}': "
                    f"claude={claude.get(field)!r} cursor={cursor.get(field)!r}")

    validate_json_file(ROOT / "hooks" / "hooks.json", "Claude hooks")
    validate_json_file(ROOT / "hooks" / "cursor-hooks.json", "Cursor hooks")
    validate_hook_parity()
    validate_skills()
    validate_md_components("agents", require_name=True, is_agent=True)
    validate_md_components("commands", require_name=False)
    validate_rules()
    validate_routing_surface()
    validate_doc_inventories()
    validate_tie_break_parity()
    validate_squawk_scaffold()
    validate_evals()


URL_RE = re.compile(r"https?://[^\s<>()\[\]`\"']+")
LINK_SOURCES = ("skills", "agents", "rules", "docs", "README.md", "AGENTS.md")


def collect_urls():
    """Every external URL cited in components and docs, with one file that cites it. Templated
    URLs (an `NN` placeholder, a `{ver}` slot, an angle-bracket slot) are skipped whole."""
    seen = {}
    for src in LINK_SOURCES:
        path = ROOT / src
        if not path.exists():
            continue
        files = [path] if path.is_file() else sorted(path.rglob("*.md")) + sorted(path.rglob("*.mdc"))
        for f in files:
            if "plans" in f.parts or "research" in f.parts:
                continue  # gitignored working notes are not published citations
            text = f.read_text()
            for m in URL_RE.finditer(text):
                url = m.group(0).rstrip(".,;:")
                if "NN" in url or "{" in url or text[m.end():m.end() + 1] == "<":
                    continue
                seen.setdefault(url, f.relative_to(ROOT))
    return seen


# Delay before the one retry `resolve_url` grants a transport error or a 429/503. A module-level
# constant so `--selftest` can zero it for the local fixture.
RETRY_DELAY = 1.0


def _fetch(url: str, method: str) -> int:
    req = urllib.request.Request(url, method=method, headers={"User-Agent": "pgsql-coding-linkcheck/1"})
    with urllib.request.urlopen(req, timeout=20) as resp:
        return resp.status


def resolve_url(url: str):
    """Resolve one URL: HEAD first, then GET whenever HEAD fails. Within a method, a transport
    error or a 429/503 is retried once after RETRY_DELAY; any other HTTP error is a definite
    answer for that method. Returns `(status, last_reason)`."""
    status, last = None, None
    for method in ("HEAD", "GET"):
        for attempt in (1, 2):
            try:
                status = _fetch(url, method)
                break
            except urllib.error.HTTPError as e:
                last = f"HTTP {e.code}"
                if e.code in (429, 503) and attempt == 1:
                    time.sleep(RETRY_DELAY)
                    continue
                break
            except Exception as e:  # noqa: BLE001 (a reset or timeout is retried once, then GET)
                last = type(e).__name__
                if attempt == 1:
                    time.sleep(RETRY_DELAY)
                    continue
                break
        if status is not None:
            break
    return status, last


def check_links() -> int:
    """Resolve every cited URL and report the ones that never resolve. Needs the network, so it
    is a separate switch and a separate CI job: a moved page is a hole in a rule's provenance."""
    urls = collect_urls()
    broken = []
    for url, where in sorted(urls.items()):
        status, last = resolve_url(url)
        if status is None or status >= 400:
            broken.append((url, where, last or f"HTTP {status}"))
    for url, where, why in broken:
        print(f"BROKEN {url}  ({where}): {why}")
    print(f"{'FAIL' if broken else 'OK'}: {len(urls) - len(broken)} of {len(urls)} cited URLs resolve")
    return 1 if broken else 0


class _FetchFixtureServer(http.server.ThreadingHTTPServer):
    """A loopback-only HTTP server for the fetch-policy self-test."""
    daemon_threads = True

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.hits = {"flaky": 0, "busy": 0}

    def handle_error(self, request, client_address):
        pass  # /flaky drops the connection on purpose; its flush error is expected


class _FetchFixtureHandler(http.server.BaseHTTPRequestHandler):
    """/ok resolves; /head-refused fails HEAD but resolves on GET; /missing is a hard 404; /flaky
    drops its first connection, then resolves; /busy answers 503 once, then resolves."""

    def log_message(self, *_args):
        pass

    def do_HEAD(self):
        self._route("HEAD")

    def do_GET(self):
        self._route("GET")

    def _route(self, method):
        if self.path == "/ok":
            self._reply(200)
        elif self.path == "/head-refused":
            self._reply(405 if method == "HEAD" else 200)
        elif self.path == "/flaky" and self.server.hits["flaky"] == 0:
            self.server.hits["flaky"] += 1
            self.close_connection = True
            self.wfile.close()
        elif self.path == "/busy" and self.server.hits["busy"] == 0:
            self.server.hits["busy"] += 1
            self._reply(503)
        elif self.path in ("/flaky", "/busy"):
            self._reply(200)
        else:
            self._reply(404)

    def _reply(self, code):
        self.send_response(code)
        self.end_headers()


def _selftest_fetch_policy() -> int:
    global RETRY_DELAY
    real_delay, RETRY_DELAY = RETRY_DELAY, 0
    server = _FetchFixtureServer(("127.0.0.1", 0), _FetchFixtureHandler)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    try:
        base = f"http://127.0.0.1:{server.server_port}"
        cases = (("/ok", False), ("/head-refused", False), ("/flaky", False), ("/busy", False), ("/missing", True))
        mismatches = []
        for path, expect_broken in cases:
            status, last = resolve_url(base + path)
            if (status is None or status >= 400) != expect_broken:
                mismatches.append(f"{path}: status={status} last={last}")
        for mismatch in mismatches:
            print(f"FAIL link fetch policy: {mismatch}")
        if not mismatches:
            print("ok   link fetch policy: HEAD/GET fallback, transport retry, 503 retry, hard 404")
        return len(mismatches)
    finally:
        server.shutdown()
        server.server_close()
        RETRY_DELAY = real_delay


SELFTEST_HOOKS_CLAUDE = {"hooks": {"PostToolUse": [{"matcher": "Write|Edit", "hooks": [
    {"type": "command", "command": "bash ${CLAUDE_PLUGIN_ROOT}/hooks/a.sh"}]}]}}
SELFTEST_HOOKS_CURSOR = {"hooks": {"afterFileEdit": [{"command": "bash hooks/a.sh"}]}}


def _selftest_tree(root: Path, *, break_it=None):
    """Write a minimal but valid plugin tree, then apply one deliberate defect. Synthetic, so a
    self-test never passes because the real tree happens to be shaped a certain way."""
    for d in ("skills/pgsql-thing/references", "skills/pgsql-coding", "skills/pgsql-lint-setup",
              "agents", "rules", "hooks", "references", "docs", "evals/thing-case/graders"):
        (root / d).mkdir(parents=True)
    desc = {"frontmatter_colon": "a: colon",
            "description_folded": ">-\n  " + "x" * 600 + "\n  " + "y" * 600}.get(break_it, "does a thing")
    name = "pgsql-other" if break_it == "skill_name" else "pgsql-thing"
    link = "" if break_it == "reference_unlinked" else "Read [topic.md](references/topic.md).\n"
    (root / "skills/pgsql-thing/SKILL.md").write_text(f"---\nname: {name}\ndescription: {desc}\n---\n\n{link}")
    sources = "" if break_it == "reference_no_sources" else "## Sources\n\n- x\n"
    (root / "skills/pgsql-thing/references/topic.md").write_text(f"# Topic\n\n## Rules\n\n- y\n\n{sources}")
    tie_ok = TIE_BREAK_SENTENCE
    tie_bad = TIE_BREAK_SENTENCE.replace("then the shorter statement", "then the faster statement")
    routed = "" if break_it == "router_missing_skill" else "pgsql-thing "
    (root / "skills/pgsql-coding/SKILL.md").write_text(
        f"---\nname: pgsql-coding\ndescription: router\n---\n\n{routed}pgsql-lint-setup. Order: {tie_ok}.\n")
    (root / CURSOR_RULE).write_text(
        f"---\ndescription: rule\n---\n\npgsql-thing pgsql-lint-setup. Order: {tie_ok}.\n")
    tools = "allowed-tools:" if break_it == "agent_tools" else "tools:"
    (root / REVIEWER).write_text(
        f"---\nname: pgsql-reviewer\ndescription: reviews\n{tools} Read\n---\n\npgsql-thing. Order: "
        f"{tie_bad if break_it == 'tie_break' else tie_ok}.\n")
    toml = 'pg_version = "18"\n'
    (root / SQUAWK_REFERENCE).write_text(toml)
    scaffold = toml + ("excluded_rules = []\n" if break_it == "squawk_drift" else "")
    (root / SQUAWK_SCAFFOLD).write_text(
        f"---\nname: pgsql-lint-setup\ndescription: scaffolds\n---\n\n```toml\n{scaffold}```\n")
    script = root / "hooks" / "a.sh"
    script.write_text("#!/usr/bin/env bash\nexit 0\n")
    script.chmod(0o644 if break_it == "hook_not_executable" else 0o755)
    (root / BANNER).write_text("echo pgsql-thing\n")
    (root / BANNER).chmod(0o755)
    claude = json.loads(json.dumps(SELFTEST_HOOKS_CLAUDE))
    claude["hooks"]["SessionStart"] = [{"hooks": [{"type": "command", "command": f"bash ${{CLAUDE_PLUGIN_ROOT}}/{BANNER}"}]}]
    cursor = json.loads(json.dumps(SELFTEST_HOOKS_CURSOR))
    cursor["hooks"]["sessionStart"] = [{"command": f"bash {BANNER}"}]
    if break_it == "hook_parity":
        cursor["hooks"]["afterFileEdit"] = []
    if break_it == "cursor_plugin_root":
        cursor["hooks"]["afterFileEdit"] = [{"command": "bash ${CLAUDE_PLUGIN_ROOT}/hooks/a.sh"}]
    if break_it == "claude_relative":
        claude["hooks"]["PostToolUse"][0]["hooks"][0]["command"] = "bash hooks/a.sh"
    (root / "hooks/hooks.json").write_text(json.dumps(claude))
    if break_it != "hook_config_missing":
        (root / "hooks/cursor-hooks.json").write_text(json.dumps(cursor))
    inventory = "" if break_it == "doc_inventory" else "pgsql-thing "
    for doc in ("README.md", "AGENTS.md", "docs/testing.md", "docs/install.md"):
        (root / doc).write_text(f"# Doc\n\n{inventory}pgsql-coding pgsql-lint-setup pgsql-reviewer a session-start\n")
    (root / "evals/thing-case/prompt.md").write_text("---\ndescription: case\n---\n\nAsk.\n")
    skill = "pgsql-nope" if break_it == "eval_skill" else "pgsql-thing"
    (root / "evals/thing-case/graders/skill-fired.md").write_text(
        f"---\ntype: tool_used\ntool: Skill\ninput_match: '\"skill\"\\s*:\\s*\"(?:[\\w-]+:)?{skill}\"'\n---\n")
    agent = "pgsql-nobody" if break_it == "eval_agent" else "pgsql-reviewer"
    (root / "evals/thing-case/graders/agent.md").write_text(
        f"---\ntype: tool_used\ntool: Agent\ninput_match: '\"subagent_type\"\\s*:\\s*\"(?:[\\w-]+:)?{agent}\"'\n---\n")
    ref = "(topic|missing)" if break_it == "eval_reference" else "(topic)"
    (root / "evals/thing-case/graders/read-reference.md").write_text(
        f"---\ntype: regex\ntarget: trace\npattern: '\"(file_path|path)\"\\s*:\\s*\"[^\"]*pgsql-thing/references/{ref}\\.md\"'\n---\n")


SELFTEST_CASES = (
    ("hook wired for one host only", "hook_parity", (validate_hook_parity,)),
    ("wired hook not executable", "hook_not_executable", (validate_hook_parity,)),
    ("one host's hook config is missing", "hook_config_missing", (validate_hook_parity,)),
    ("Cursor hook command uses CLAUDE_PLUGIN_ROOT", "cursor_plugin_root", (validate_hook_parity,)),
    ("Claude hook command is workspace-relative", "claude_relative", (validate_hook_parity,)),
    ("folded description over the limit", "description_folded", (validate_skills,)),
    ("shipped skill missing from the docs", "doc_inventory", (validate_doc_inventories,)),
    ("unquoted ': ' in a description", "frontmatter_colon", (validate_skills,)),
    ("skill name != directory", "skill_name", (validate_skills,)),
    ("reference not linked from SKILL.md", "reference_unlinked", (validate_skills,)),
    ("reference without a Sources section", "reference_no_sources", (validate_skills,)),
    ("router does not name a focused skill", "router_missing_skill", (validate_routing_surface,)),
    ("agent declares allowed-tools", "agent_tools",
     (lambda: validate_md_components("agents", require_name=True, is_agent=True),)),
    ("tie-break sentence drifts between files", "tie_break", (validate_tie_break_parity,)),
    ("squawk scaffold drifts from the reference", "squawk_drift", (validate_squawk_scaffold,)),
    ("eval expects a skill that does not ship", "eval_skill", (validate_evals,)),
    ("eval expects a reference that does not exist", "eval_reference", (validate_evals,)),
    ("eval expects an agent that does not ship", "eval_agent", (validate_evals,)),
)


def run_selftest() -> int:
    """Every structural check, run against a tree built to break it, and against the same tree
    with the defect removed, so a check that never fires and a check that always fires both fail."""
    global ROOT, errors
    real_root, real_errors, failures = ROOT, errors, 0
    with tempfile.TemporaryDirectory() as tmp:
        ROOT = Path(tmp)
        (ROOT / "README.md").write_text(
            "See <https://example.com/a>. Docs at `https://www.postgresql.org/docs/NN/x.html` "
            "and `https://example.com/{ver}/x`.\n")
        got = set(collect_urls())
    ROOT = real_root
    if got == {"https://example.com/a"}:
        print("ok   link collector skips templated URLs whole")
    else:
        print(f"FAIL link collector: collected {sorted(got)}")
        failures += 1
    failures += _selftest_fetch_policy()
    for label, defect, checks in SELFTEST_CASES:
        outcomes = {}
        for variant, break_it in (("broken", defect), ("clean", None)):
            with tempfile.TemporaryDirectory() as tmp:
                ROOT = Path(tmp)
                _selftest_tree(ROOT, break_it=break_it)
                errors = []
                for check in checks:
                    check()
                outcomes[variant] = list(errors)
        ROOT, errors = real_root, real_errors
        if not outcomes["broken"]:
            print(f"FAIL {label}: the check did not catch it")
            failures += 1
        elif outcomes["clean"]:
            print(f"FAIL {label}: the check also fires on a clean tree: {outcomes['clean'][0]}")
            failures += 1
        else:
            print(f"ok   {label}")
    if failures:
        print(f"FAIL: {failures} check(s) do not actually check")
        return 1
    print(f"OK: {len(SELFTEST_CASES)} structural checks each caught their own failure case")
    return 0


if __name__ == "__main__":
    if "--selftest" in sys.argv[1:]:
        sys.exit(run_selftest())
    if "--check-links" in sys.argv[1:]:
        sys.exit(check_links())
    main()
    if errors:
        print(f"FAIL: {len(errors)} problem(s)")
        for e in errors:
            print(f"  - {e}")
        sys.exit(1)
    print("OK: manifests, dual-host parity, component paths, kebab-case names, hook configs and "
          "parity, skills and their references, agents, rules, the routing surface, doc "
          "inventories, the tie-break sentence, the squawk scaffold, and eval cases are valid")
