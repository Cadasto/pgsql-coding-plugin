# Idioms: queries that return the right rows

Read when: a query compares with NULL, uses `IN`, `NOT IN`, `EXISTS`, `ANY`, `LEFT JOIN`, `LATERAL`, `WITH` or `WITH RECURSIVE`, a window function, `FILTER`, `DISTINCT ON`, `LIMIT` or `OFFSET`, a `timestamptz` range, `AT TIME ZONE` or `now()`.

Deterministic backstop: none. These forms all run without error and return wrong rows. Prove them with a test against PostgreSQL 18 (see `testing.md`). Plan cost belongs to `pgsql-performance`.

## Contents

- NULL logic
- Joins, subqueries and evaluation order
- CTEs and recursion
- Window functions and aggregates
- Ordering and pagination
- Time
- Newer in PostgreSQL 19 (hints)

## NULL logic

- **`NOT IN` over a list of non-null constants is safe.** The subquery form is SKILL.md's rule; its cost at scale is `pgsql-performance`'s.
- **`IN` and `= ANY` return null, not false, when the right side holds a null and nothing matches** ([subqueries](https://www.postgresql.org/docs/18/functions-subquery.html), [array comparisons](https://www.postgresql.org/docs/18/functions-comparisons.html)). Under `NOT`, that null still filters the row out.
- **`count(*)` counts rows; `count(col)` counts non-null values** ([aggregates](https://www.postgresql.org/docs/18/functions-aggregate.html)).

```sql
SELECT c.id, c.name
FROM customers c
WHERE NOT EXISTS (
  SELECT FROM orders o
  WHERE o.customer_id = c.id
    AND o.placed_at >= $1 AND o.placed_at < $2
);
```

## Joins, subqueries and evaluation order

- **Use `EXISTS` for "has at least one", not `JOIN` plus `DISTINCT`.** Only whether a row exists matters, so the output list is irrelevant; `SELECT 1` is the convention ([subqueries](https://www.postgresql.org/docs/18/functions-subquery.html)).
- **Use `LEFT JOIN LATERAL (...) ON true` for "top N per parent".** `LATERAL` lets the subquery reference earlier `FROM` items, and the left join keeps parents with no rows ([table expressions](https://www.postgresql.org/docs/18/queries-table-expressions.html)).
- **Put a condition on the right-hand table of a `LEFT JOIN` in `ON`, not in `WHERE`.** A restriction in `ON` is processed before the join and one in `WHERE` after it, so `WHERE o.status = 'paid'` discards the null-extended rows and turns the left join into an inner join ([joined tables](https://www.postgresql.org/docs/18/queries-table-expressions.html#QUERIES-JOIN)).
- **Do not rely on `AND` short-circuiting in `WHERE`.** Evaluation order is undefined and Boolean expressions are reordered. Guard a division or cast with `CASE`, or remove the division (`x > 0 AND y > 1.5 * x` instead of `x > 0 AND y / x > 1.5`). A `CASE` cannot stop an aggregate inside it from running; filter with `WHERE` or `FILTER` ([expression evaluation](https://www.postgresql.org/docs/18/sql-expressions.html#SYNTAX-EXPRESS-EVAL)).

```sql
SELECT p.id, last3.*
FROM projects p
LEFT JOIN LATERAL (
  SELECT e.kind, e.created_at
  FROM events e
  WHERE e.project_id = p.id
  ORDER BY e.created_at DESC, e.id DESC
  LIMIT 3
) last3 ON true;
```

## CTEs and recursion

- **A plain `WITH` is not an optimisation fence.** A side-effect-free, non-recursive CTE referenced once is folded into the parent query; one referenced twice is computed once. `MATERIALIZED` forces separate computation and `NOT MATERIALIZED` forces folding ([WITH queries](https://www.postgresql.org/docs/18/queries-with.html)). Write either keyword only when a plan shows the default is wrong.
- **Data-modifying CTEs run exactly once, to completion, on one snapshot.** Sibling statements cannot see each other's changes to the target tables, and their order is unpredictable. Pass rows between them with `RETURNING` ([WITH queries](https://www.postgresql.org/docs/18/queries-with.html)).
- **Give a recursive walk over data that can loop a `CYCLE` clause.** `CYCLE id SET is_cycle USING path` stops at a repeated row. `SEARCH DEPTH FIRST BY id SET ordercol` (or `BREADTH FIRST`) gives an order column to sort by ([WITH queries](https://www.postgresql.org/docs/18/queries-with.html)).

```sql
WITH RECURSIVE tree AS (
  SELECT id, parent_id FROM nodes WHERE id = $1
  UNION ALL
  SELECT n.id, n.parent_id FROM nodes n JOIN tree t ON n.parent_id = t.id
) CYCLE id SET is_cycle USING path
SELECT id FROM tree WHERE NOT is_cycle;
```

## Window functions and aggregates

- **`last_value` returns the current row unless the frame is widened.** The default frame runs from the partition start to the current row's last peer. Add `ROWS BETWEEN UNBOUNDED PRECEDING AND UNBOUNDED FOLLOWING`, or use `first_value` with the order reversed ([window functions](https://www.postgresql.org/docs/18/functions-window.html), [window calls](https://www.postgresql.org/docs/18/sql-expressions.html#SYNTAX-WINDOW-FUNCTIONS)).
- **Use `FILTER (WHERE ...)` for conditional aggregates.** Only rows where the filter is true reach the aggregate: `count(*) FILTER (WHERE status = 'failed')` ([aggregate expressions](https://www.postgresql.org/docs/18/sql-expressions.html#SYNTAX-AGGREGATES)).
- **`DISTINCT ON (a)` needs `ORDER BY a, <tie-break>`.** The `DISTINCT ON` expressions must match the leftmost `ORDER BY` expressions. Without an order the kept row is unpredictable ([SELECT](https://www.postgresql.org/docs/18/sql-select.html#SQL-DISTINCT)).

```sql
SELECT DISTINCT ON (device_id) device_id, reading, measured_at
FROM readings
ORDER BY device_id, measured_at DESC, id DESC;
```

## Ordering and pagination

- **Page with a keyset: compare a row constructor with the last row seen.** Row comparison goes left to right and stops at the first unequal pair, so keep the key columns `NOT NULL` ([row comparison](https://www.postgresql.org/docs/18/functions-comparisons.html#ROW-WISE-COMPARISON)). The matching index belongs to `pgsql-indexing`.

```sql
SELECT id, created_at, title
FROM posts
WHERE (created_at, id) < ($1, $2)
ORDER BY created_at DESC, id DESC
LIMIT 50;
```

## Time

- **`TIMESTAMP '...+01'` drops the offset.** PostgreSQL silently ignores a zone in a value typed `timestamp without time zone`, so `TIMESTAMP '2026-10-27 10:00+01'` means 10:00 in no zone. An untyped literal compared with or stored in a `timestamptz` keeps its offset. Write `TIMESTAMPTZ '2026-10-27 10:00+01'`, or pass a typed driver value ([date/time types](https://www.postgresql.org/docs/18/datatype-datetime.html)).
- **Compute local day or month boundaries with a zone, not the session.** `date_trunc('day', ts, 'Europe/Amsterdam')` truncates in that zone. `ts AT TIME ZONE 'Europe/Amsterdam'` turns an instant into that zone's wall time, and the reverse turns a wall time into an instant ([date/time functions](https://www.postgresql.org/docs/18/functions-datetime.html#FUNCTIONS-DATETIME-ZONECONVERT)).
- **`now()` is the transaction start time.** It does not move inside a transaction. Use `clock_timestamp()` for elapsed-time measurement inside one ([current time](https://www.postgresql.org/docs/18/functions-datetime.html#FUNCTIONS-DATETIME-CURRENT)).

## Newer in PostgreSQL 19 (hints)

PostgreSQL 19 is a release candidate. These are hints, not rules ([release notes](https://www.postgresql.org/docs/19/release-19.html)).

- `lead`, `lag`, `first_value`, `last_value` and `nth_value` accept `IGNORE NULLS` and `RESPECT NULLS`. PostgreSQL 18 does not implement them ([window functions](https://www.postgresql.org/docs/18/functions-window.html)).
- `random(min, max)` gains `date`, `timestamp` and `timestamptz` versions.
- `GROUP BY` handles target-list subqueries whose expressions reference non-subquery columns.

## Sources

- PostgreSQL 18 manual (checked 2026-10-27): [subquery expressions](https://www.postgresql.org/docs/18/functions-subquery.html), [row and array comparisons](https://www.postgresql.org/docs/18/functions-comparisons.html), [aggregate functions](https://www.postgresql.org/docs/18/functions-aggregate.html), [table expressions](https://www.postgresql.org/docs/18/queries-table-expressions.html), [value expressions](https://www.postgresql.org/docs/18/sql-expressions.html), [WITH queries](https://www.postgresql.org/docs/18/queries-with.html), [window functions](https://www.postgresql.org/docs/18/functions-window.html), [SELECT](https://www.postgresql.org/docs/18/sql-select.html), [date/time types](https://www.postgresql.org/docs/18/datatype-datetime.html), [date/time functions](https://www.postgresql.org/docs/18/functions-datetime.html)
- PostgreSQL 19 release notes, as of 2026-10-09: <https://www.postgresql.org/docs/19/release-19.html> (checked 2026-10-27)
