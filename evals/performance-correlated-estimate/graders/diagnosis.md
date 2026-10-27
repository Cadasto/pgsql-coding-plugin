---
type: llm
weight: 2
---

PASS if the answer does all of the following:
- names the row misestimate on `orders` (about 600 estimated against 48,210 actual) as the root problem, and explains that it made the planner pick a nested loop whose inner `customers_pkey` lookup runs 48,210 times (`loops=48210`), which is most of the execution time;
- attributes the misestimate to `country` and `city` being correlated while the planner treats the two conditions as independent;
- recommends `CREATE STATISTICS` on `(country, city)` of `orders` (kind `dependencies` or `mcv`, or no kind listed), followed by `ANALYZE orders`, and says to re-run `EXPLAIN (ANALYZE, BUFFERS)` to confirm the estimate and the join change.

FAIL if any of these holds:
- it recommends raising `work_mem` as a fix (the sort already ran in memory);
- its only fix is the composite index on `(country, city)`, without addressing the estimate;
- it recommends `enable_nestloop = off` or another `enable_*` setting as the fix;
- it presents `CREATE STATISTICS` as effective without running `ANALYZE` afterwards.
