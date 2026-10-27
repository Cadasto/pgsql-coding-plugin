# Index design

Read when: a task decides which columns an index holds and in what order, adds a partial, expression, covering (`INCLUDE`) or unique index, relies on skip scan or an index-only scan, matches an `ORDER BY`, indexes a foreign key, or weighs an index against write cost and HOT updates.

Backstop: `EXPLAIN (ANALYZE, BUFFERS)` after `ANALYZE` shows `Index Cond`, `Index Searches`, `Heap Fetches` and any `Sort`; reading the plan belongs to `pgsql-performance`.

## Contents

- Column order and skip scan
- `OR` conditions and combining indexes
- Partial indexes
- Expression indexes
- Covering indexes and index-only scans
- Sort order
- Uniqueness and NULLs
- Foreign keys
- Write cost, HOT and fillfactor

## Column order and skip scan

- **Skip scan helps only a low-cardinality leading column.** PostgreSQL 18 can probe each distinct value of a leading column that has no condition, but "if there are many distinct `x` values, then the entire index will have to be scanned", and the planner then prefers a sequential scan ([multicolumn indexes](https://www.postgresql.org/docs/18/indexes-multicolumn.html), [release notes](https://www.postgresql.org/docs/18/release-18.html)). The `Index Searches` line of `EXPLAIN ANALYZE` counts the probes ([using EXPLAIN](https://www.postgresql.org/docs/18/using-explain.html)). A query that filters only on a high-cardinality column still needs an index that leads with it.
- **Prefer one to three key columns.** Most cases need one; more than three rarely helps ([multicolumn indexes](https://www.postgresql.org/docs/18/indexes-multicolumn.html)). For GIN and BRIN the column order does not matter; for GiST the first column decides most of the scan ([multicolumn indexes](https://www.postgresql.org/docs/18/indexes-multicolumn.html)).

## `OR` conditions and combining indexes

- **`OR` on one column becomes `= ANY(array)`.** PostgreSQL 18 transforms such `OR` clauses into arrays for index processing ([release notes](https://www.postgresql.org/docs/18/release-18.html)); `tenant = 1 OR tenant = 3` ran as `Index Cond: (tenant = ANY ('{1,3}'))` (checked).
- **`OR` across columns needs an index per column.** An index on `(a, b)` cannot serve `a = 5 OR b = 6` directly; the planner combines separate index scans with a bitmap `OR`, and the bitmap loses index order, so an `ORDER BY` needs a sort ([combining indexes](https://www.postgresql.org/docs/18/indexes-bitmap-scans.html)).
- **Composite or separate is a workload choice.** A composite `(x, y)` beats combining two indexes when both columns are filtered, but helps less for `y` alone; `(x, y)` plus `(y)` can serve both ([combining indexes](https://www.postgresql.org/docs/18/indexes-bitmap-scans.html)).

## Partial indexes

- **The query must imply the predicate at planning time.** "Parameterized query clauses do not work with a partial index", and the planner proves only simple inequality implications (`x < 1` implies `x < 2`); otherwise the predicate must match part of the `WHERE` clause exactly ([partial indexes](https://www.postgresql.org/docs/18/indexes-partial.html)). A generic plan for `WHERE status = $1` ignored an index `WHERE status = 'active'`, while the same query with the literal used it (checked).

  ```sql
  CREATE INDEX orders_pending_created_idx ON orders (created_at) WHERE status = 'pending';
  -- the query repeats the literal: WHERE status = 'pending' AND created_at < $1
  ```

- **Use partial indexes to skip the common value.** Index the rare rows (`WHERE deleted_at IS NULL` when most rows are deleted, `WHERE status = 'pending'` when most are done) to keep the index small ([partial indexes](https://www.postgresql.org/docs/18/indexes-partial.html)).
- **Do not imitate partitioning with many partial indexes.** The planner tests each one; a single index on `(category, data)` is better, and a table too large for one index wants partitioning ([partial indexes](https://www.postgresql.org/docs/18/indexes-partial.html)).

## Expression indexes

- **Query the exact expression the index stores.** The manual's example indexes `lower(col1)` for `WHERE lower(col1) = 'value'` ([expression indexes](https://www.postgresql.org/docs/18/indexes-expressional.html)); `email ILIKE 'x'` did not use an index on `lower(email)` (checked).
- **Every function in the expression or predicate must be IMMUTABLE.** Results must "never" depend on outside influence such as the current time ([CREATE INDEX](https://www.postgresql.org/docs/18/sql-createindex.html)). Functions that depend on the `TimeZone` setting are STABLE ([volatility](https://www.postgresql.org/docs/18/xfunc-volatility.html)), so `created_at::date` on a `timestamptz` fails with "functions in index expression must be marked IMMUTABLE"; fix the zone instead. Never mark a function IMMUTABLE just to get it indexed.

  ```sql
  CREATE INDEX events_day_idx ON events (((created_at AT TIME ZONE 'UTC')::date));
  -- WHERE (created_at AT TIME ZONE 'UTC')::date = $1
  ```

- **Expressions cost every insert and non-HOT update.** They are computed on write, not on search ([expression indexes](https://www.postgresql.org/docs/18/indexes-expressional.html)).

## Covering indexes and index-only scans

- **An index-only scan needs every referenced column in the index and an all-visible page.** Otherwise each row is checked in the table; tables with heavy updates gain less ([index-only scans](https://www.postgresql.org/docs/18/indexes-index-only-scans.html)). `Heap Fetches` in `EXPLAIN ANALYZE` counts the table visits; it fell from 999 to 0 after a `VACUUM` set the visibility map (checked).
- **`INCLUDE` adds payload, not search keys.** Included columns cannot be searched, are ignored by uniqueness, need no operator class, cannot be expressions, and exist only on B-tree, GiST and SP-GiST; B-tree deduplication is off for such indexes; an index entry that exceeds the size limit fails the insert ([CREATE INDEX](https://www.postgresql.org/docs/18/sql-createindex.html)).

  ```sql
  CREATE UNIQUE INDEX accounts_email_idx ON accounts (email) INCLUDE (display_name);
  ```

- **An expression index needs its source column included for an index-only scan.** The planner only considers columns, so index `(f(x)) INCLUDE (x)` ([index-only scans](https://www.postgresql.org/docs/18/indexes-index-only-scans.html)).

## Sort order

- **An index matching `ORDER BY ... LIMIT n` returns the first rows without sorting the rest** ([ordering](https://www.postgresql.org/docs/18/indexes-ordering.html)).
- **Declare directions for mixed orders.** `(x, y)` serves `ORDER BY x, y` and, backwards, `ORDER BY x DESC, y DESC`, but not `ORDER BY x, y DESC`; declare `(x, y DESC)` ([ordering](https://www.postgresql.org/docs/18/indexes-ordering.html)). The mismatched index produced an `Incremental Sort` (checked). Defaults are `ASC NULLS LAST`, so `DESC` scans give `NULLS FIRST`; match `NULLS LAST` explicitly when the query asks for it.

## Uniqueness and NULLs

- **A partial unique index enforces a rule on a subset**, for example one active subscription per account ([partial indexes](https://www.postgresql.org/docs/18/indexes-partial.html)).

  ```sql
  CREATE UNIQUE INDEX subscriptions_one_active_idx ON subscriptions (account_id) WHERE ended_at IS NULL;
  ```

## Foreign keys

- **The referenced side is always indexed.** A foreign key must point at a primary key, unique constraint or non-partial unique index ([constraints](https://www.postgresql.org/docs/18/ddl-constraints.html)); `maintenance.md` lists referencing columns without an index.

## Write cost, HOT and fillfactor

- **Each index slows every write and can block HOT updates.** HOT needs an update that changes no indexed column (BRIN excepted) and free space on the page ([introduction](https://www.postgresql.org/docs/18/indexes-intro.html), [HOT](https://www.postgresql.org/docs/18/storage-hot.html)). Do not index a column that changes on most updates unless queries need it.
- **Leave room for HOT on update-heavy tables.** A lower table `fillfactor` raises the chance of HOT updates ([HOT](https://www.postgresql.org/docs/18/storage-hot.html)); `pg_stat_user_tables.n_tup_hot_upd` against `n_tup_upd` shows the ratio. B-tree indexes default to fillfactor 90; 100 is best for a static table ([CREATE INDEX](https://www.postgresql.org/docs/18/sql-createindex.html)).

## Sources

- Multicolumn indexes: <https://www.postgresql.org/docs/18/indexes-multicolumn.html> (checked 2026-10-27)
- Combining multiple indexes: <https://www.postgresql.org/docs/18/indexes-bitmap-scans.html> (checked 2026-10-27)
- Partial indexes: <https://www.postgresql.org/docs/18/indexes-partial.html> (checked 2026-10-27)
- Expression indexes: <https://www.postgresql.org/docs/18/indexes-expressional.html> (checked 2026-10-27)
- Index-only scans and covering indexes: <https://www.postgresql.org/docs/18/indexes-index-only-scans.html> (checked 2026-10-27)
- Indexes and `ORDER BY`: <https://www.postgresql.org/docs/18/indexes-ordering.html> (checked 2026-10-27)
- Introduction (write cost): <https://www.postgresql.org/docs/18/indexes-intro.html> (checked 2026-10-27)
- Constraints (foreign keys): <https://www.postgresql.org/docs/18/ddl-constraints.html> (checked 2026-10-27)
- CREATE INDEX: <https://www.postgresql.org/docs/18/sql-createindex.html> (checked 2026-10-27)
- Function volatility: <https://www.postgresql.org/docs/18/xfunc-volatility.html> (checked 2026-10-27)
- Heap-only tuples: <https://www.postgresql.org/docs/18/storage-hot.html> (checked 2026-10-27)
- Using `EXPLAIN` (`Index Searches`): <https://www.postgresql.org/docs/18/using-explain.html> (checked 2026-10-27)
- PostgreSQL 18 release notes: <https://www.postgresql.org/docs/18/release-18.html> (checked 2026-10-27)
- Behaviour marked "checked" was run on PostgreSQL 18.6 (2026-10-27).
