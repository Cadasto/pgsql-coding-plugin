# Rewrites a plan justifies

Read when: a plan points at the shape of the statement rather than at missing statistics or a missing index: `NOT IN` with a subquery, a function or cast on a filtered column, a parameter of another type than its column, a growing `OFFSET`, `COUNT(*)` over a large table, `OR` across different columns, a CTE referenced more than once, or a `SubPlan` that runs once per outer row.

Backstop: `EXPLAIN (ANALYZE, BUFFERS)` before and after; a test that proves the rewritten statement returns the same rows, including when columns are NULL. How to write each form in application code is in `pgsql-query`.

## Contents

- NOT IN with a subquery
- A function or cast on the filtered column
- OFFSET paging
- COUNT(*) on a large table
- OR across different columns
- CTEs referenced more than once
- A SubPlan per outer row
- Newer in PostgreSQL 19 (hints)
- Sources

## NOT IN with a subquery

- **Evidence:** `Filter: (NOT (ANY (... (hashed SubPlan 1) ...)))` or a plain `SubPlan` under a filter ([Using EXPLAIN](https://www.postgresql.org/docs/18/using-explain.html)); or rows silently missing.
- **Why:** the planner "can't transform it into an anti-join"; the hashed form is allowed only for small results, and the plain form is O(N²), so a fast test can turn slow "once a size threshold is crossed" ([Don't Do This](https://wiki.postgresql.org/wiki/Don%27t_Do_This)). The NULL trap is `pgsql-query`'s rule.
- **Rewrite:** `NOT EXISTS`. A literal `NOT IN (1, 2, 3)` list with no NULL is fine.

```sql
SELECT c.id FROM customers AS c
WHERE NOT EXISTS (SELECT 1 FROM orders AS o WHERE o.customer_id = c.id);
```

## A function or cast on the filtered column

- **Evidence:** a `Seq Scan` with `Filter: (lower(email) = ...)`, `Filter: (date(created_at) = ...)` or `Filter: ((id)::numeric = ...)` although an index on the column exists.
- **Why:** a B-tree is considered "whenever an indexed column is involved in a comparison" with `<`, `<=`, `=`, `>=` or `>` ([Index Types](https://www.postgresql.org/docs/18/indexes-types.html)). A function or cast applied to the column makes the comparison one on an expression, which only an index on that same expression serves ([Indexes on Expressions](https://www.postgresql.org/docs/18/indexes-expressional.html)).
- **Rewrite:** move the work to the constant side. Turn a date match into a half-open range whose bounds are computed in a named zone, or passed as two `timestamptz` parameters from the application; bind parameters with the column's own type so no cast lands on the column (driver details in `pgsql-query`). When the expression is the real requirement (`lower(email)`), add an expression index through `pgsql-indexing` instead.
- **Name the zone.** `created_at::date` and a bare `$1::date` bound both take the day from the session `TimeZone`; a date compared with a timestamp "is assumed to represent midnight in the `TimeZone` zone" ([Date/Time Functions](https://www.postgresql.org/docs/18/functions-datetime.html)). `timestamp AT TIME ZONE 'zone'` returns the `timestamptz` of that local time in the named zone ([AT TIME ZONE](https://www.postgresql.org/docs/18/functions-datetime.html#FUNCTIONS-DATETIME-ZONECONVERT)), so the bounds no longer depend on the session. The same row matched under the `UTC`, `Europe/Amsterdam` and `America/New_York` session zones (checked).

```sql
-- before: WHERE created_at::date = $1
WHERE created_at >= ($1::date)::timestamp AT TIME ZONE 'Europe/Amsterdam'
  AND created_at <  (($1::date) + 1)::timestamp AT TIME ZONE 'Europe/Amsterdam'
```

## OFFSET paging

- **Evidence:** page latency grows with the page number; the plan reads `OFFSET + LIMIT` rows and discards most of them.
- **Why:** offsets skip or repeat rows when data changes between pages (Markus Winand, [No Offset](https://use-the-index-luke.com/no-offset)).
- **Rewrite:** keyset paging with a row comparison on a unique sort key, backed by an index on the same columns in the same order; PostgreSQL uses the index for row comparisons (Markus Winand, [Fetch the next page](https://use-the-index-luke.com/sql/partial-results/fetch-next-page)). It cannot jump to page N; offer "next" and "previous".

```sql
SELECT id, created_at, total FROM orders
WHERE (created_at, id) < ($1, $2)
ORDER BY created_at DESC, id DESC
LIMIT 50;
```

## COUNT(*) on a large table

- **Evidence:** a full `Seq Scan` or `Index Only Scan` over every row to show a total in a UI.
- **Why:** PostgreSQL "has to check visibility for all rows, due to the MVCC model" ([Count estimate](https://wiki.postgresql.org/wiki/Count_estimate)).
- **Rewrite, when an estimate is acceptable:** read `pg_class.reltuples` for a whole table, or the planner's `rows` from `EXPLAIN (FORMAT JSON)` for a filtered count. Both are only as fresh as the last `VACUUM` or `ANALYZE` ([Count estimate](https://wiki.postgresql.org/wiki/Count_estimate)). Never build that `EXPLAIN` text from user input. Keep the exact count where the number is a contract, such as billing.

```sql
SELECT reltuples::bigint AS estimate FROM pg_class WHERE oid = 'public.orders'::regclass;
```

## OR across different columns

- **Evidence:** a `Seq Scan` with `Filter: ((a = ...) OR (b = ...))`.
- **Why:** one index scan uses only `AND`-ed clauses on its columns; for `OR` the planner can combine separate index scans with a bitmap `OR`, but only when each arm has a usable index, and the combined result loses index order ([Combining Multiple Indexes](https://www.postgresql.org/docs/18/indexes-bitmap-scans.html)). PostgreSQL 18 already turns `OR`s on one column into an array for faster index processing ([release notes 18](https://www.postgresql.org/docs/18/release-18.html)), so do not hand-rewrite `a = 1 OR a = 2`.
- **Rewrite:** give each arm an index (`pgsql-indexing`), then confirm a `BitmapOr` in the plan.

## CTEs referenced more than once

- **Evidence:** a `CTE Scan` with a `Filter` over a large CTE, while the base table has an index on the filtered column.
- **Why:** a side-effect-free, non-recursive CTE referenced once is folded into the outer query; one referenced more than once is materialised, and outer conditions are not pushed into it ([WITH Queries](https://www.postgresql.org/docs/18/queries-with.html)). PostgreSQL 18 shows memory and disk use for CTE nodes ([release notes 18](https://www.postgresql.org/docs/18/release-18.html)).
- **Rewrite:** `WITH w AS NOT MATERIALIZED (...)` lets the outer conditions reach the base table. Keep or add `MATERIALIZED` when the CTE computes an expensive expression that inlining would evaluate twice ([WITH Queries](https://www.postgresql.org/docs/18/queries-with.html)).

## A SubPlan per outer row

- **Evidence:** a `SubPlan` in the target list or a filter whose `loops` equals the outer row count; actual time per loop times `loops` is the cost ([Using EXPLAIN](https://www.postgresql.org/docs/18/using-explain.html)).
- **Rewrite:** express it as a join or a `LEFT JOIN LATERAL` so the planner can choose the join method, then compare the plans. Keep the rewrite only if the plan and the timing improve.

## Newer in PostgreSQL 19 (hints)

Release candidate only ([release notes 19](https://www.postgresql.org/docs/19/release-19.html)):

- `NOT IN` becomes an anti-join when NULLs are not present, and more `LEFT JOIN`s become anti-joins. `NOT EXISTS` stays correct on every version, so keep the rule.
- Some aggregation can run before joins, reducing the rows processed.

## Sources

- Using EXPLAIN: <https://www.postgresql.org/docs/18/using-explain.html> (checked 2026-10-27)
- PostgreSQL wiki, Don't Do This, "Don't use NOT IN": <https://wiki.postgresql.org/wiki/Don%27t_Do_This> (checked 2026-10-27)
- Index Types: <https://www.postgresql.org/docs/18/indexes-types.html> (checked 2026-10-27)
- Indexes on Expressions: <https://www.postgresql.org/docs/18/indexes-expressional.html> (checked 2026-10-27)
- Date/Time Functions, AT TIME ZONE: <https://www.postgresql.org/docs/18/functions-datetime.html> (checked 2026-10-27)
- Markus Winand, No Offset: <https://use-the-index-luke.com/no-offset>; Fetch the next page: <https://use-the-index-luke.com/sql/partial-results/fetch-next-page> (checked 2026-10-27)
- PostgreSQL wiki, Count estimate: <https://wiki.postgresql.org/wiki/Count_estimate> (checked 2026-10-27)
- Combining Multiple Indexes: <https://www.postgresql.org/docs/18/indexes-bitmap-scans.html> (checked 2026-10-27)
- WITH Queries, CTE materialization: <https://www.postgresql.org/docs/18/queries-with.html> (checked 2026-10-27)
- PostgreSQL 18 release notes: <https://www.postgresql.org/docs/18/release-18.html> (checked 2026-10-27)
- PostgreSQL 19 release notes, as of 2026-10-09: <https://www.postgresql.org/docs/19/release-19.html> (checked 2026-10-27)
- Behaviour marked "checked" was run on PostgreSQL 18.6 (2026-10-27).
