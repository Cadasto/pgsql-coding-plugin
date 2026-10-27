---
type: llm
weight: 2
---

PASS only if the final answer does both:
1. Says the new index is not used to read `orders` in the after plan (it is still a Parallel Seq Scan with the same filter), and attributes the speed-up to the corrected row estimate for the `doc->>'channel'` filter (833 estimated before, about 55,845 after, from the statistics ANALYZE gathered on the index expression), which let the planner replace the nested loop of about 133,333 primary-key lookups with a hash join.
2. Names at least one remaining problem with its fix: the sort spilling to disk in every worker and the hash using 8 batches instead of the planned 1 (more `work_mem` for this query, for example `SET LOCAL`), or the `customers` filter estimated at 2,001 rows but returning 10,000 because `country` and `city` are correlated (`CREATE STATISTICS` with dependencies, then ANALYZE).

FAIL if it says the index scan itself made the query faster, if its main recommendation is another index on the channel key, or if it names neither remaining problem.
