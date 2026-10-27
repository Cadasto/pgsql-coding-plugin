#!/usr/bin/env python3
"""Summarise a PostgreSQL EXPLAIN plan: where the time went and which nodes look wrong.

Reads one plan in TEXT or JSON format (EXPLAIN (ANALYZE, BUFFERS) or EXPLAIN (ANALYZE,
BUFFERS, FORMAT JSON)), from a file or stdin, including psql's aligned output with its
"QUERY PLAN" header and "(N rows)" footer. Prints the totals, the nodes with the most exclusive
time, and findings: row misestimates, sorts and hashes that spilled to disk, nodes run many
times, filters that discard most rows, heap fetches in index-only scans, workers that did not
launch, and JIT overhead. A plan without ANALYZE has estimates only, and says so.

The numbers are arithmetic on the plan, not a diagnosis: "time x loops" over-counts parallel
nodes (each worker is a loop), and exclusive time is a node's time minus its children's.
Read the flagged nodes with the pgsql-performance explain.md reference before deciding a fix.

Standard library only (Python 3.9+). Usage:
    plan-summary.py [--top N] [PLAN_FILE | -]
"""
import argparse
import json
import re
import sys

NODE_RE = re.compile(
    r"^(?P<name>.+?)\s+\(cost=[\d.]+\.\.[\d.]+ rows=(?P<est>[\d.]+) width=\d+\)"
    r"(?:\s+\(actual (?:time=(?P<start>[\d.]+)\.\.(?P<total>[\d.]+) )?rows=(?P<rows>[\d.]+) loops=(?P<loops>\d+)\)"
    r"|\s+\((?P<never>never executed)\))?")
SUMMARY_HEADS = ("Planning", "Execution Time", "JIT", "Triggers", "Trigger ", "Settings", "Serialization", "Query Identifier")


class Node:
    def __init__(self, name, ref, est=None, rows=None, loops=None, total=None, never=False):
        self.name, self.ref, self.est, self.rows, self.loops = name, ref, est, rows, loops
        self.total, self.never, self.children, self.attrs = total, never, [], {}

    @property
    def analyzed(self):
        return self.rows is not None

    @property
    def work_ms(self):  # time x loops: the node's share of the run, children included
        return (self.total or 0.0) * (self.loops or 0)

    @property
    def exclusive_ms(self):
        return max(0.0, self.work_ms - sum(c.work_ms for c in self.children))


def strip_psql(text):
    """Drop psql's aligned-format decoration: the QUERY PLAN header, the dashed rule, the
    '(N rows)' footer, the one-space left margin, and the '+' that marks a wrapped JSON line."""
    lines = text.splitlines()
    out = []
    for line in lines:
        if re.match(r"^\s*QUERY PLAN\s*$", line) or re.match(r"^-{5,}\+?$", line.strip()):
            continue
        if re.match(r"^\(\d+ rows?\)$", line.strip()):
            continue
        out.append(re.sub(r"\s*\+$", "", line))
    while out and not out[0].strip():
        out.pop(0)
    margin = min((len(l) - len(l.lstrip(" ")) for l in out if l.strip()), default=0)
    return [l[margin:] for l in out]


def parse_text(lines):
    root, stack, summary, in_summary, current = None, [], {}, False, None
    for i, line in enumerate(lines, 1):
        if not line.strip():
            continue
        indent = len(line) - len(line.lstrip(" "))
        body = line.strip()
        if indent == 0 and root is not None and body.startswith(SUMMARY_HEADS):
            in_summary = True
        if in_summary:
            m = re.match(r"^(Planning|Execution) Time: ([\d.]+) ms", body)
            if m:
                summary[m.group(1)] = float(m.group(2))
            m = re.search(r"Timing:.*Total ([\d.]+) ms", body)
            if m:
                summary["JIT"] = float(m.group(1))
            continue
        arrow = body.startswith("->")
        if root is None or arrow:
            m = NODE_RE.match(body[2:].strip() if arrow else body)
            if not m:
                continue
            node = Node(m.group("name").strip(), f"line {i}", float(m.group("est")),
                        float(m.group("rows")) if m.group("rows") else None,
                        int(m.group("loops")) if m.group("loops") else None,
                        float(m.group("total")) if m.group("total") else None, bool(m.group("never")))
            col = indent if arrow else -1
            while stack and stack[-1][0] >= col:
                stack.pop()
            if stack:
                stack[-1][1].children.append(node)
            else:
                root = node
            stack.append((col, node))
            current = node
            continue
        if current is not None:
            attrs = current.attrs
            for key, val in re.findall(r"(Rows Removed by (?:Filter|Join Filter|Index Recheck)|Heap Fetches|"
                                       r"Workers Planned|Workers Launched|Index Searches|Batches): (\d+)", body):
                attrs[key] = max(attrs.get(key, 0), int(val)) if key == "Batches" else int(val)
            m = re.search(r"Batches: \d+ \(originally (\d+)\)", body)
            if m:
                attrs["Batches planned"] = int(m.group(1))
            m = re.search(r"Sort Method: ([a-z -]+?)\s+(Disk|Memory): (\d+)kB", body)
            if m and m.group(2) == "Disk":
                attrs.setdefault("spill", []).append(f"{m.group(1)} {m.group(3)}kB on disk")
            m = re.match(r"Buffers: (.*)", body)
            if m and "buffers" not in attrs:
                attrs["buffers"] = m.group(1)
    return root, summary


def parse_json(text):
    data = json.loads(text)
    doc = data[0] if isinstance(data, list) else data
    counter = [0]

    def build(p):
        counter[0] += 1
        name = ("Parallel " if p.get("Parallel Aware") else "") + p.get("Node Type", "?")
        if p.get("Relation Name"):
            via = f" using {p['Index Name']}" if p.get("Index Name") else ""
            name += f"{via} on {p['Relation Name']}" + (f" {p['Alias']}" if p.get("Alias") not in (None, p["Relation Name"]) else "")
        elif p.get("Index Name"):
            name += f" on {p['Index Name']}"
        never = p.get("Actual Loops") == 0
        node = Node(name, f"node #{counter[0]}", p.get("Plan Rows"), p.get("Actual Rows"), p.get("Actual Loops"),
                    p.get("Actual Total Time"), never)
        a = node.attrs
        for key in ("Rows Removed by Filter", "Rows Removed by Join Filter", "Rows Removed by Index Recheck",
                    "Heap Fetches", "Workers Planned", "Workers Launched", "Index Searches"):
            if key in p:
                a[key] = p[key]
        if p.get("Hash Batches", 1) > 1:
            a["Batches"] = p["Hash Batches"]
            if p.get("Original Hash Batches", p["Hash Batches"]) != p["Hash Batches"]:
                a["Batches planned"] = p["Original Hash Batches"]
        for s in [p] + list(p.get("Workers", [])):
            if s.get("Sort Space Type") == "Disk":
                a.setdefault("spill", []).append(f"{s.get('Sort Method')} {s.get('Sort Space Used')}kB on disk")
        if "Shared Hit Blocks" in p:
            a["buffers"] = (f"shared hit={p['Shared Hit Blocks']} read={p.get('Shared Read Blocks', 0)}"
                            + (f", temp read={p['Temp Read Blocks']} written={p['Temp Written Blocks']}"
                               if p.get("Temp Written Blocks") else ""))
        node.children = [build(c) for c in p.get("Plans", [])]
        return node

    summary = {k: doc[f"{k} Time"] for k in ("Planning", "Execution") if f"{k} Time" in doc}
    jit = (doc.get("JIT") or {}).get("Timing", {}).get("Total")
    if jit is not None:
        summary["JIT"] = jit
    return build(doc["Plan"]), summary


def walk(node):
    yield node
    for c in node.children:
        yield from walk(c)


def misestimate(n):
    """(ratio, direction) when actual and estimated rows per loop differ tenfold or more on a node
    that handled enough rows to matter; None otherwise."""
    if not n.analyzed or n.never:
        return None
    est, rows, loops = n.est or 0.0, n.rows or 0.0, n.loops or 1
    hi, lo = max(est, rows), max(min(est, rows), 1.0)
    if hi / lo >= 10 and hi * loops >= 1000:
        return hi / lo, ("under" if rows > est else "over")
    return None


def findings(root, summary):
    out, carried = [], []
    for n in walk(root):
        if not n.analyzed or n.never:
            continue
        a, loops = n.attrs, n.loops or 1
        est, rows = n.est or 0.0, n.rows or 0.0
        miss = misestimate(n)
        if miss:
            ratio, way = miss
            below = [m[0] for m in map(misestimate, n.children) if m and m[1] == way]
            if not below:  # the lowest node with the error: where the fix starts
                out.append((ratio * 10, f"[{n.ref}] {way}estimate x{ratio:.0f} starts here: {n.name} estimated "
                                        f"{est:g} rows per loop, got {rows:g} (loops {loops})"))
            elif ratio / max(below) >= 3:  # inherited, but this node adds its own error on top
                out.append((ratio, f"[{n.ref}] {way}estimate grows here from x{max(below):.0f} to x{ratio:.0f}: "
                                   f"{n.name} (its own join or filter selectivity is off too)"))
            else:
                carried.append(f"{n.name} x{ratio:.0f} [{n.ref}]")
        if a.get("spill"):
            out.append((50, f"[{n.ref}] spilled to disk: {n.name}: {'; '.join(a['spill'])}"))
        if a.get("Batches", 1) > 1:
            planned = (f"planned {a['Batches planned']} batch{'es' if a['Batches planned'] > 1 else ''}, used "
                       f"{a['Batches']} (more build rows than estimated, or work_mem too small)"
                       if "Batches planned" in a else f"{a['Batches']} batches")
            out.append((50, f"[{n.ref}] hash spilled to disk, {planned}: {n.name}"))
        if loops >= 1000 and n is not root:
            out.append((loops / 100, f"[{n.ref}] runs {loops:,} times: {n.name}, {n.total:g} ms each = "
                                     f"{n.work_ms:.1f} ms of work"))
        removed = a.get("Rows Removed by Filter", 0) * loops
        kept = rows * loops
        if removed >= 10000 and removed / (removed + kept) >= 0.5:
            out.append((removed / 10000, f"[{n.ref}] filter discards {removed:,.0f} of {removed + kept:,.0f} rows "
                                         f"({removed / (removed + kept):.0%}): {n.name}"))
        if "Index Only" in n.name and a.get("Heap Fetches", 0) * loops >= 1000:
            out.append((5, f"[{n.ref}] index-only scan fetched {a['Heap Fetches'] * loops:,} heap rows "
                           f"(visibility map not set): {n.name}"))
        if a.get("Workers Launched", a.get("Workers Planned", 0)) < a.get("Workers Planned", 0):
            out.append((5, f"[{n.ref}] {a['Workers Launched']} of {a['Workers Planned']} planned workers launched: {n.name}"))
    if carried:
        out.append((1, f"[carried] the estimate error above flows up through: {', '.join(carried)}"))
    jit, exe = summary.get("JIT"), summary.get("Execution")
    if jit and exe and jit / exe >= 0.1:
        out.append((jit / exe * 100, f"[summary] JIT took {jit:.1f} ms of {exe:.1f} ms execution ({jit / exe:.0%})"))
    return [text for _, text in sorted(out, key=lambda x: -x[0])]


def main():
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("plan", nargs="?", default="-", help="plan file, or - for stdin")
    ap.add_argument("--top", type=int, default=5, help="nodes to list by exclusive time")
    args = ap.parse_args()
    text = sys.stdin.read() if args.plan == "-" else open(args.plan, encoding="utf-8").read()
    lines = strip_psql(text)
    body = "\n".join(lines).strip()
    try:
        root, summary = parse_json(body) if body[:1] in "[{" else parse_text(lines)
    except (ValueError, KeyError, IndexError) as e:
        print(f"Could not parse the plan ({type(e).__name__}: {e}). Pass the plain output of EXPLAIN.")
        return 2
    if root is None:
        print("No plan found. Pass the output of EXPLAIN (ANALYZE, BUFFERS) in TEXT or JSON format.")
        return 2
    nodes = list(walk(root))
    head = [f"Plan: {len(nodes)} nodes"]
    for k in ("Execution", "Planning", "JIT"):
        if k in summary:
            head.append(f"{k.lower()} {summary[k]:.1f} ms")
    print(" · ".join(head))
    if not root.analyzed:
        print("Estimates only: this plan has no actual rows or times. Run EXPLAIN (ANALYZE, BUFFERS) "
              "(inside BEGIN ... ROLLBACK for a write) before deciding a fix.")
        return 0
    if not any(n.attrs.get("buffers") for n in nodes):
        print("No Buffers lines: add BUFFERS to see shared hit, read and temp blocks.")
    print(f"\nTop {min(args.top, len(nodes))} nodes by exclusive time (time x loops, children subtracted; "
          f"parallel workers each count as a loop):")
    ranked = sorted((n for n in nodes if n.analyzed and not n.never), key=lambda n: -n.exclusive_ms)
    for i, n in enumerate(ranked[:args.top], 1):
        buf = f"; buffers {n.attrs['buffers']}" if n.attrs.get("buffers") else ""
        print(f"  {i}. [{n.ref}] {n.name}: {n.exclusive_ms:.1f} ms exclusive, {n.work_ms:.1f} ms with children, "
              f"rows {n.rows:g} (est {n.est:g}), loops {n.loops}{buf}")
    found = findings(root, summary)
    print("\nFindings:" if found else "\nFindings: none of the mechanical checks fired.")
    for f in found:
        print(f"  - {f}")
    never = [n for n in nodes if n.never]
    if never:
        print(f"\nNever executed: {', '.join(f'[{n.ref}] {n.name}' for n in never)}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
