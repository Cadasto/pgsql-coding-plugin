#!/usr/bin/env python3
"""Tests for skills/pgsql-performance/scripts/plan-summary.py against real PostgreSQL 18.6 plans.

The fixtures in scripts/testdata/plans/ were produced by EXPLAIN (ANALYZE, BUFFERS) on a
postgres:18 container, in TEXT and JSON format. Run: python3 scripts/plan-summary-test.py
(exit 0 = all pass). Standard library only.
"""
import re
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SCRIPT = ROOT / "skills" / "pgsql-performance" / "scripts" / "plan-summary.py"
PLANS = ROOT / "scripts" / "testdata" / "plans"
fails = 0


def run(stdin_text=None, path=None, *extra):
    args = [sys.executable, str(SCRIPT), *extra] + ([str(path)] if path else ["-"])
    p = subprocess.run(args, input=stdin_text, capture_output=True, text=True)
    return p.returncode, p.stdout


def check(name, cond, detail=""):
    global fails
    if cond:
        print(f"ok   {name}")
    else:
        fails += 1
        print(f"FAIL {name}{': ' + detail if detail else ''}")


def kinds(out):
    """The findings with node references and run-specific numbers removed, so a TEXT and a
    JSON plan of the same query compare equal."""
    found = out.split("Findings:", 1)[-1]
    lines = [l for l in found.splitlines() if l.startswith("  - ")]
    return sorted(re.sub(r"\[[^\]]*\]|[\d.,]+(ms|kB| ms)?", "", l).replace("Parallel ", "") for l in lines)


def names(out):
    """The node names in the time ranking, which both formats must spell alike."""
    return sorted(re.findall(r"^  \d+\. \[[^\]]*\] (.+?): [\d.]+ ms exclusive", out, re.MULTILINE))


code, text = run(path=PLANS / "join-spill.txt")
check("text plan parses", code == 0 and "Plan: 5 nodes" in text, text)
check("misestimate is traced to the lowest node",
      "underestimate x53 starts here: Parallel Seq Scan on orders o" in text, text)
check("a join that adds its own error is called out", "grows here from x53 to x269: Nested Loop" in text, text)
check("inherited misestimates are carried, not repeated",
      "flows up through: Gather Merge" in text and text.count("starts here") == 1, text)
check("a sort that spilled in every worker is reported",
      "spilled to disk: Sort" in text and text.count("on disk") == 3, text)
check("an inner node run many times is reported", "runs 133,333 times: Index Scan using customers_pkey" in text, text)
check("a filter that discards most rows is reported", "filter discards 266,667 of 400,000 rows" in text, text)
check("text references point at plan lines", "[line 13]" in text, text)
check("nodes are ranked by exclusive time, children subtracted",
      "1. [line 17] Index Scan using customers_pkey on customers c: 133.3 ms exclusive" in text
      and "Nested Loop: 0.0 ms exclusive, 188.1 ms with children" in text, text)

code, js = run(path=PLANS / "join-spill.json")
check("JSON plan parses", code == 0 and "Plan: 5 nodes" in js, js)
check("JSON names a parallel scan as the text format does", "Parallel Seq Scan on orders o" in js, js)
check("TEXT and JSON plans of one query give the same findings", kinds(text) == kinds(js),
      f"{kinds(text)} != {kinds(js)}")

# psql's aligned output: a QUERY PLAN header, a dashed rule, a one-space margin, a row-count
# footer, and '+' at the end of each wrapped JSON line.
raw = (PLANS / "join-spill.txt").read_text().splitlines()
aligned = "                QUERY PLAN\n" + "-" * 60 + "\n" + "\n".join(" " + l for l in raw) + f"\n({len(raw)} rows)\n"
code, out = run(stdin_text=aligned)
check("psql aligned TEXT output parses like the plain plan", code == 0 and kinds(out) == kinds(text), out)
raw_js = (PLANS / "join-spill.json").read_text().splitlines()
aligned_js = "  QUERY PLAN\n" + "-" * 20 + "\n" + "\n".join(" " + l + " +" for l in raw_js) + "\n(1 row)\n"
code, out = run(stdin_text=aligned_js)
check("psql aligned JSON output parses like the plain plan", code == 0 and kinds(out) == kinds(js), out)

code, out = run(path=PLANS / "subplan-loops.txt")
check("a correlated subplan's loops are reported", "runs 3,000 times: Aggregate" in out, out)
check("JIT overhead is reported when it is a large share", "JIT took 14.2 ms of 114.6 ms" in out, out)
check("a filter that discards almost everything is reported", "filter discards 216,000 of 219,000 rows (99%)" in out, out)

code, out = run(path=PLANS / "join-after-index.txt")
check("a hash that grew past its planned batches is reported",
      "hash spilled to disk, planned 1 batch, used 8" in out, out)

code, out = run(path=PLANS / "subplan-loops.json")
check("JIT under a tenth of execution is not reported", "jit 3.8 ms" in out and "JIT took" not in out, out)

# Every plan captured in both formats gives the same node names and the same findings. JIT time
# differs from run to run, so its share is left out of the comparison.
for txt in sorted(PLANS.glob("*.txt")):
    if not txt.with_suffix(".json").exists():
        continue
    t_out, j_out = run(None, txt, "--top", "99")[1], run(None, txt.with_suffix(".json"), "--top", "99")[1]
    check(f"{txt.stem}: TEXT and JSON name the nodes alike", names(t_out) == names(j_out),
          f"{names(t_out)} != {names(j_out)}")
    t_kinds, j_kinds = ([k for k in kinds(o) if "JIT took" not in k] for o in (t_out, j_out))
    check(f"{txt.stem}: TEXT and JSON give the same findings", t_kinds == j_kinds, f"{t_kinds} != {j_kinds}")
out = run(None, PLANS / "join-filter.json", "--top", "99")[1]
check("JSON names a two-phase aggregate as TEXT does", "Finalize Aggregate" in out and "Partial Aggregate" in out, out)
out = run(None, PLANS / "semi-stop.json", "--top", "99")[1]
check("JSON folds the join type into the node name as TEXT does", "Nested Loop Semi Join" in out, out)

# Defects found in review, each on a real 18.6 plan.
for ext in ("txt", "json"):
    code, out = run(path=PLANS / f"timing-off.{ext}")
    check(f"a TIMING OFF plan ({ext}) is summarised without a ranking by time",
          code == 0 and "No per-node times" in out and "Top " not in out, out)
    check(f"TIMING OFF ({ext}): the loops finding leaves out the missing time",
          "runs 4,000 times: Index Only Scan using o_cid_amt on o\n" in out, out)
code, out = run(path=PLANS / "heap-fetch.txt")
check("heap fetches are a total, not multiplied by loops", "fetched 39,994 heap rows" in out, out)
code, out = run(path=PLANS / "join-filter.txt")
check("a join filter that discards most rows is reported",
      "join filter discards 128,282 of 149,996 rows (86%): Hash Join" in out, out)
code, out = run(path=PLANS / "limit-stop.txt")
check("a scan a LIMIT stopped early is not an overestimate", "overestimate" not in out, out)
code, out = run(path=PLANS / "limit-sort.txt")
check("a Sort a LIMIT stopped early is not an overestimate", not re.search(r"overestimate.*: (Limit|Sort) ", out), out)
check("an overestimate below a Sort under a LIMIT is still reported",
      "overestimate x5103 starts here: Seq Scan on o estimated 5103 rows per loop, got 0" in out, out)
code, out = run(path=PLANS / "semi-stop.txt")
check("a semi join's inner side, stopping at the first match, is not an overestimate", "overestimate" not in out, out)
code, out = run(path=PLANS / "fractional-probe.txt")
check("a fractional row count is compared as it is, not rounded up to one",
      "overestimate x21 starts here: Index Only Scan using o_cid_amt on o" in out, out)
code, out = run(path=PLANS / "clamp-probe.txt")
check("an estimate of one row, the planner's floor, is not called an overestimate",
      "overestimate x27 starts here: Nested Loop" in out and "starts here: Index Scan" not in out, out)
for name, expect in (("hashagg-spill", "hash spilled to disk, 85 batches: HashAggregate"),
                     ("window-store", "spilled to disk: WindowAgg: stored rows 5274kB on disk"),
                     ("incr-sort", "spilled to disk: Incremental Sort: external merge 576kB on disk")):
    for ext in ("txt", "json"):
        code, out = run(path=PLANS / f"{name}.{ext}")
        check(f"{name}.{ext}: the spill is reported", expect in out, out)

code, out = run(path=PLANS / "estimate-only.txt")
check("a plan without ANALYZE says it has estimates only", code == 0 and "Estimates only" in out, out)

code, out = run(stdin_text="this is not a plan\n")
check("input that is not a plan exits 2 with a hint", code == 2 and "No plan found" in out, out)
code, out = run(stdin_text="[{\"Plan\": \n")
check("broken JSON exits 2 with a hint", code == 2 and "Could not parse" in out, out)

# Can-fail control: the comparison helper must tell different findings apart, or the
# TEXT-versus-JSON check above would pass on anything.
check("can-fail: kinds() distinguishes different findings",
      kinds("Findings:\n  - [line 1] spilled to disk: Sort\n") != kinds("Findings:\n  - [line 1] runs 5 times: Sort\n"))
check("can-fail: names() reads the ranking",
      names("  1. [line 1] Sort: 1.0 ms exclusive\n") == ["Sort"] and names("Findings: none\n") == [])

sys.exit(1 if fails else 0)
