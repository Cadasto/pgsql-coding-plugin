# Planner statistics

Read when: estimated and actual rows differ widely in a plan; a plan changed after a bulk load, a big delete or a major upgrade; two filtered columns are correlated (city and zip code, tenant and status); a `GROUP BY` over several columns is misestimated; a filter uses an expression such as `date_trunc(...)` or `lower(...)`; or a temporary or partitioned table plans badly.

Backstop: the `rows=` estimate against the actual rows in `EXPLAIN (ANALYZE, BUFFERS)`; the `pg_stats` view; `n_mod_since_analyze` and `last_autoanalyze` in `pg_stat_user_tables`.

## Contents

- Fresh statistics
- Reading pg_stats
- Per-column targets and overrides
- Correlated columns and expressions
- Newer in PostgreSQL 19 (hints)
- Sources

## Fresh statistics

- **`ANALYZE` after a large change, not later.** Plans rely on `pg_statistic` being up to date, and after substantial changes the manual advises a manual `ANALYZE` rather than waiting for autovacuum ([EXPLAIN](https://www.postgresql.org/docs/18/sql-explain.html)). `ANALYZE` samples rows, so it is cheap ([Routine Vacuuming](https://www.postgresql.org/docs/18/routine-vacuuming.html)). Run it at the end of a bulk load or backfill.
- **Know when autoanalyze fires.** It runs once the rows inserted, updated or deleted since the last analyze exceed `autovacuum_analyze_threshold` (default 50) plus `autovacuum_analyze_scale_factor` (default 0.1) times the row count ([Routine Vacuuming](https://www.postgresql.org/docs/18/routine-vacuuming.html), [Vacuuming settings](https://www.postgresql.org/docs/18/runtime-config-vacuum.html)). On a 100-million-row table that is 10 million changes. Lower the scale factor per table with a storage parameter when the newest rows drive the hot queries:

```sql
ALTER TABLE events SET (autovacuum_analyze_scale_factor = 0.01);
```

- **Analyze temporary tables explicitly.** "Temporary tables cannot be accessed by autovacuum" ([Routine Vacuuming](https://www.postgresql.org/docs/18/routine-vacuuming.html)). Fill, then `ANALYZE`, then query.
- **Analyze partitioned parents explicitly.** Changes in partitions "do not trigger analyze on the parent table"; run `ANALYZE` on the partitioned table after the first load and whenever the distribution across partitions changes ([Routine Vacuuming](https://www.postgresql.org/docs/18/routine-vacuuming.html)).
- **Check freshness before blaming the planner.** `pg_stat_user_tables.n_mod_since_analyze` is the estimated rows changed since the last analyze; `last_autoanalyze` is when autovacuum last analyzed ([Cumulative Statistics](https://www.postgresql.org/docs/18/monitoring-stats.html)).

```sql
SELECT relname, n_live_tup, n_mod_since_analyze, last_autoanalyze
FROM pg_stat_user_tables
WHERE relname = 'orders';
```

## Reading pg_stats

- **Use `pg_stats`, not `pg_statistic`.** It is readable by all and shows only tables the user may read ([pg_stats](https://www.postgresql.org/docs/18/view-pg-stats.html)).
- **Know the columns that drive estimates** ([pg_stats](https://www.postgresql.org/docs/18/view-pg-stats.html)):
  - `null_frac`: fraction of NULLs.
  - `n_distinct`: above zero, the distinct count; below zero, minus the fraction of rows that are distinct (`-1` is unique).
  - `most_common_vals` and `most_common_freqs`: the frequent values and their share of rows.
  - `histogram_bounds`: equal-population buckets for the remaining values; used for ranges.
  - `correlation`: physical order versus logical order, from -1 to +1. Near 0 makes index range scans look more expensive.

```sql
SELECT attname, null_frac, n_distinct, most_common_vals, most_common_freqs, correlation
FROM pg_stats
WHERE schemaname = 'public' AND tablename = 'orders' AND attname IN ('tenant_id', 'status');
```

## Per-column targets and overrides

- **Raise the target on the skewed column, not globally.** `default_statistics_target` (default 100) caps the entries in `most_common_vals` and `histogram_bounds`; a larger value improves estimates for irregular distributions at the cost of `ANALYZE` time and space ([Statistics Used by the Planner](https://www.postgresql.org/docs/18/planner-stats.html), [Query Planning settings](https://www.postgresql.org/docs/18/runtime-config-query.html)). Per column the range is 0 to 10000, and the change takes a `SHARE UPDATE EXCLUSIVE` lock ([ALTER TABLE](https://www.postgresql.org/docs/18/sql-altertable.html)). It applies from the next `ANALYZE`:

```sql
ALTER TABLE orders ALTER COLUMN tenant_id SET STATISTICS 1000;
ANALYZE orders;
```

- **Override `n_distinct` when sampling gets it wrong.** `SET (n_distinct = ...)` fixes the estimate: a positive value is an exact count, a value from -1 to below 0 is a fraction of the rows (`-0.5` means each value appears twice). Use `n_distinct_inherited` for partitioned tables ([ALTER TABLE](https://www.postgresql.org/docs/18/sql-altertable.html)).

## Correlated columns and expressions

- **The planner assumes conditions are independent.** For correlated columns, "the query planner will assume that the conditions are independent, resulting in underestimating the result size" ([Statistics Used by the Planner](https://www.postgresql.org/docs/18/planner-stats.html)). The symptom is an estimate far below the actual rows on a filter over two or more columns, often followed by a nested loop with a huge `loops`.
- **Pick the kind that matches the query** ([Statistics Used by the Planner](https://www.postgresql.org/docs/18/planner-stats.html), [CREATE STATISTICS](https://www.postgresql.org/docs/18/sql-createstatistics.html)):
  - `dependencies`: equality to constants and `IN` with constants. Not used for ranges, `LIKE`, column-to-column comparisons or expressions.
  - `mcv`: common combinations of values in conditions on several columns, including value pairs that never occur together.
  - `ndistinct`: `GROUP BY` over several columns or expressions.
  Omitting the kinds builds all three. Create them only for column sets that queries filter or group on together and that cause bad plans.
- **`CREATE STATISTICS` does nothing until `ANALYZE`.** It "merely creates a catalog entry"; `ANALYZE` collects the data ([Statistics Used by the Planner](https://www.postgresql.org/docs/18/planner-stats.html)):

```sql
CREATE STATISTICS orders_country_city (dependencies, mcv) ON country, city FROM orders;
ANALYZE orders;
```

- **Statistics on an expression without an index.** `CREATE STATISTICS ... ON (expression) FROM table` gives the planner statistics for that expression, "similar to creating an index on the expression, except that they avoid the overhead of index maintenance" ([CREATE STATISTICS](https://www.postgresql.org/docs/18/sql-createstatistics.html)). Use it when a filter on `date_trunc('month', created_at)` or `lower(email)` is misestimated but an index would not be used:

```sql
CREATE STATISTICS events_month ON (date_trunc('month', created_at)) FROM events;
ANALYZE events;
```

- **Confirm with the plan.** Re-run `EXPLAIN (ANALYZE, BUFFERS)` and check the estimate moved toward the actual rows; the manual's examples do exactly this ([CREATE STATISTICS](https://www.postgresql.org/docs/18/sql-createstatistics.html)).

## Newer in PostgreSQL 19 (hints)

Release candidate only ([release notes 19](https://www.postgresql.org/docs/19/release-19.html)):

- Extended statistics on virtual generated columns.
- `pg_restore_extended_stats()` and `pg_clear_extended_stats()`; `pg_dump` can include restorable extended statistics.

## Sources

- Statistics Used by the Planner (14.2): <https://www.postgresql.org/docs/18/planner-stats.html> (checked 2026-10-27)
- CREATE STATISTICS: <https://www.postgresql.org/docs/18/sql-createstatistics.html> (checked 2026-10-27)
- ALTER TABLE, `SET STATISTICS`, `n_distinct`: <https://www.postgresql.org/docs/18/sql-altertable.html> (checked 2026-10-27)
- pg_stats view: <https://www.postgresql.org/docs/18/view-pg-stats.html> (checked 2026-10-27)
- Query Planning settings, `default_statistics_target`: <https://www.postgresql.org/docs/18/runtime-config-query.html> (checked 2026-10-27)
- Vacuuming settings, autovacuum thresholds: <https://www.postgresql.org/docs/18/runtime-config-vacuum.html> (checked 2026-10-27)
- Routine Vacuuming, temporary and partitioned tables: <https://www.postgresql.org/docs/18/routine-vacuuming.html> (checked 2026-10-27)
- Cumulative Statistics, `pg_stat_all_tables`: <https://www.postgresql.org/docs/18/monitoring-stats.html> (checked 2026-10-27)
- EXPLAIN, Notes: <https://www.postgresql.org/docs/18/sql-explain.html> (checked 2026-10-27)
- PostgreSQL 19 release notes, as of 2026-10-09: <https://www.postgresql.org/docs/19/release-19.html> (checked 2026-10-27)
