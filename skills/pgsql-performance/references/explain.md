# Reading EXPLAIN output

Read when: a task shows or asks for `EXPLAIN` or `EXPLAIN ANALYZE` output, a statement is slow and no plan exists yet, a statement is fast in `psql` but slow from the application, or a plan shows `loops` above 1, `Buffers`, a disk sort, hash `Batches`, `Index Searches`, `Heap Fetches`, a `SubPlan`, a `Gather` node or a `JIT:` block.

Backstop: the plan itself. Run `EXPLAIN (ANALYZE, BUFFERS)` on data of realistic size, before and after any change.

## Contents

- Getting a plan
- Reading a plan
- Plans for prepared statements
- Newer in PostgreSQL 19 (hints)
- Sources

## Getting a plan

- **Use `EXPLAIN (ANALYZE, BUFFERS)` to diagnose, plain `EXPLAIN` when the statement must not run.** `ANALYZE` carries out the command and shows actual times and row counts beside the estimates ([EXPLAIN](https://www.postgresql.org/docs/18/sql-explain.html)). Since PostgreSQL 18, buffer counts are included automatically with `ANALYZE` ([release notes 18](https://www.postgresql.org/docs/18/release-18.html)); writing `BUFFERS` anyway is harmless.
- **Roll back data-modifying statements.** `EXPLAIN ANALYZE` on `INSERT`, `UPDATE`, `DELETE`, `MERGE`, `CREATE TABLE AS` or `EXECUTE` changes data unless wrapped ([EXPLAIN](https://www.postgresql.org/docs/18/sql-explain.html)):

```sql
BEGIN;
EXPLAIN (ANALYZE, BUFFERS) UPDATE orders SET status = 'shipped' WHERE id = 42;
ROLLBACK;
```

- **Pick the options the question needs** ([EXPLAIN](https://www.postgresql.org/docs/18/sql-explain.html)):

| Option | Adds | With `ANALYZE` |
|---|---|---|
| `BUFFERS` | shared, local and temp blocks hit, read, dirtied, written; I/O time when `track_io_timing` is on | automatic since PG 18 |
| `VERBOSE` | output columns, schema-qualified names, the query identifier | optional |
| `SETTINGS` | planner settings that differ from the built-in default | optional |
| `WAL` | WAL records, full page images, bytes, full WAL buffers | required |
| `SERIALIZE` | time to convert the output to text or binary for the client (PG 17) | required |
| `MEMORY` | memory used by the planner (PG 17) | optional |
| `GENERIC_PLAN` | the generic plan of a statement with `$1` placeholders (PG 16) | not allowed |
| `TIMING OFF` | keeps row counts, drops per-node timing | required |
| `FORMAT JSON` | the same information, easier for programs to parse | optional |

- **Expect measurement overhead.** `EXPLAIN ANALYZE` "can sometimes take significantly longer than executing the query normally", worst for nodes that are cheap per execution and on machines with slow clock calls; `pg_test_timing` measures it ([EXPLAIN](https://www.postgresql.org/docs/18/sql-explain.html), [Using EXPLAIN](https://www.postgresql.org/docs/18/using-explain.html)). Use `TIMING OFF` when only row counts matter.
- **Do not extrapolate.** A plan from a small table does not predict the plan on a large one ([Using EXPLAIN](https://www.postgresql.org/docs/18/using-explain.html)). Test on a copy with production-like row counts and distributions.

## Reading a plan

- **Estimated versus actual rows, node by node.** Check "whether the estimated row counts are reasonably close to reality" ([Using EXPLAIN](https://www.postgresql.org/docs/18/using-explain.html)). The lowest node with a large gap is where the plan went wrong; fix it there with `statistics.md`. PostgreSQL 18 prints fractional row counts (`rows=0.50`), which are averages over loops ([release notes 18](https://www.postgresql.org/docs/18/release-18.html)).
- **Multiply by `loops`.** Actual time and rows are per-execution averages; "multiply by the `loops` value to get the total time actually spent in the node" ([Using EXPLAIN](https://www.postgresql.org/docs/18/using-explain.html)). An inner index scan at 0.05 ms with `loops=48210` costs about 2.4 s.
- **Early stops are not misestimates.** Under a `LIMIT`, or a merge join that stops early, actual rows fall below the estimate without any estimation error ([Using EXPLAIN](https://www.postgresql.org/docs/18/using-explain.html)). The inner side of a nested-loop semi or anti join (`EXISTS`, `NOT EXISTS`) stops at the first match for each outer row and shows the same gap. A `Sort`, a `Hash` or a hashed aggregate reads all its input first, so the nodes below it ran to completion (checked on 18.6).
- **`Rows Removed by Filter` is work thrown away.** It counts rows a node read and rejected; it appears only when at least one row was rejected ([Using EXPLAIN](https://www.postgresql.org/docs/18/using-explain.html)). Like the actual rows, it is an average per loop, and so is `Rows Removed by Join Filter` for a join condition the join could not use as its key (checked on 18.6). A large count beside a small output means the scan reads far more than it returns: a candidate for an index on the filter, which `pgsql-indexing` designs. `Rows Removed by Index Recheck` comes from a lossy bitmap or a lossy index.
- **`Index Searches` (PG 18) counts searches of the index across all loops.** The manual's example shows 4 searches for `thousand = ANY('{1,500,700,999}')` and 1 for `thousand IN (1, 2, 3, 4)` ([Using EXPLAIN](https://www.postgresql.org/docs/18/using-explain.html)). Compare it with `loops` before blaming the index.
- **`Buffers` counts blocks for the node and its children.** `shared hit` was in shared buffers, `read` was not; the counts are not distinct blocks ([Using EXPLAIN](https://www.postgresql.org/docs/18/using-explain.html)). A large `read` on a repeated query means the working set does not stay cached. `temp read`/`written` means a spill.
- **Sorts and hashes that spill.** The `Sort` node says whether it sorted in memory or on disk and how much space it used; the `Hash` node shows buckets and batches, and more than one batch means disk use that is not shown ([Using EXPLAIN](https://www.postgresql.org/docs/18/using-explain.html)). Both mean the node needed more than `work_mem` (times `hash_mem_multiplier`, default 2.0, for hashes) ([Resource Consumption](https://www.postgresql.org/docs/18/runtime-config-resource.html)). The same holds for `Disk Usage` on a `HashAggregate`, `Average Disk` and `Peak Disk` on an `Incremental Sort` group, and, from PG 18, `Storage: Disk` on a `Material`, `WindowAgg` or `CTE Scan` (checked on 18.6). Raise it for that query only:

```sql
BEGIN;
SET LOCAL work_mem = '64MB';
EXPLAIN (ANALYZE, BUFFERS) SELECT ...;
ROLLBACK;
```

- **`Heap Fetches` under an `Index Only Scan` are rows that still went to the table.** The scan skips the heap only for pages the visibility map marks all-visible, and `VACUUM` maintains that map ([Routine Vacuuming](https://www.postgresql.org/docs/18/routine-vacuuming.html)). Many heap fetches on a busy table point at vacuum, not at the index. The count is a total over all loops, not an average like the rows beside it ([`explain.c`](https://github.com/postgres/postgres/blob/REL_18_STABLE/src/backend/commands/explain.c)).
- **Check a `SubPlan`'s `loops`.** A value equal to the outer row count means the subquery ran once per row. `NOT (ANY (... (hashed SubPlan 1)...))` is a `NOT IN` ([Using EXPLAIN](https://www.postgresql.org/docs/18/using-explain.html)); see `rewrites.md`.
- **Planning time and execution time are separate.** Planning time excludes parsing and rewriting; execution time includes executor start-up, shut-down and triggers ([Using EXPLAIN](https://www.postgresql.org/docs/18/using-explain.html)). A slow trigger shows up in execution time, not in any scan node.
- **Disabled nodes are marked.** PostgreSQL 18 indicates nodes chosen despite a disabled planner method in `EXPLAIN ANALYZE` output ([release notes 18](https://www.postgresql.org/docs/18/release-18.html)). Check `SETTINGS` for a leftover `enable_*` before trusting such a plan.
- **Parallel plans can launch fewer workers than planned.** A `Gather` or `Gather Merge` node shows `Workers Planned`; `max_worker_processes` and `max_parallel_workers` can leave a query with fewer workers or none, and the chosen plan may then be poor ([How Parallel Query Works](https://www.postgresql.org/docs/18/how-parallel-query-works.html)). `EXPLAIN (ANALYZE, VERBOSE)` shows per-worker statistics ([Parallel Plans](https://www.postgresql.org/docs/18/parallel-plans.html)); `pg_stat_statements` compares `parallel_workers_to_launch` with `parallel_workers_launched` (PG 18).
- **A `JIT:` block is compile time paid during execution.** JIT runs when the plan cost exceeds `jit_above_cost` (default 100000; `jit` defaults to `on` in 18) ([Query Planning settings](https://www.postgresql.org/docs/18/runtime-config-query.html)). Compare `Timing: ... Total` with `Execution Time`; for short queries the overhead "will often be higher than the time it can save" ([JIT decision](https://www.postgresql.org/docs/18/jit-decision.html)). Turn it off for the role or session that runs short OLTP queries (`SET jit = off`).

## Plans for prepared statements

- **A prepared statement runs a custom or a generic plan.** By default the first five executions get custom plans; after that a generic plan is used when its estimated cost is not much higher than the custom average ([PREPARE](https://www.postgresql.org/docs/18/sql-prepare.html)). A generic plan cannot use the parameter's value, so a skewed column (one tenant with most rows) can get the wrong plan from the sixth call on.
- **pgx prepares by default.** "By default pgx uses the extended protocol and automatically prepares and caches prepared statements" ([pgx v5](https://pkg.go.dev/github.com/jackc/pgx/v5)). A statement tested in `psql` with literals is not the statement the Go service runs: from the sixth execution of a cached statement the server may use the generic plan. The driver's exec modes are in `pgsql-query`.
- **Reproduce the application's plan.** Use `EXPLAIN (GENERIC_PLAN)` on the parameterised text, or prepare and execute it six times, then `EXPLAIN EXECUTE`: a generic plan shows `$1`, a custom one the literal ([PREPARE](https://www.postgresql.org/docs/18/sql-prepare.html)). `pg_prepared_statements.generic_plans` and `custom_plans` count both for the current session ([pg_prepared_statements](https://www.postgresql.org/docs/18/view-pg-prepared-statements.html)).

```sql
EXPLAIN (GENERIC_PLAN) SELECT * FROM orders WHERE tenant_id = $1 AND status = $2;
```

- **Force custom plans only where the generic plan is measurably worse.** `plan_cache_mode` takes `auto` (default), `force_custom_plan` or `force_generic_plan` ([Query Planning settings](https://www.postgresql.org/docs/18/runtime-config-query.html)); set it with `SET LOCAL` or per session for the affected work. JIT decisions for a generic plan follow the settings in effect at prepare time ([JIT decision](https://www.postgresql.org/docs/18/jit-decision.html)).

## Newer in PostgreSQL 19 (hints)

Release candidate only; use when the project's server runs 19 ([release notes 19](https://www.postgresql.org/docs/19/release-19.html)).

- `EXPLAIN (ANALYZE, IO)` reports asynchronous I/O activity.
- `EXPLAIN` shows Memoize cache and lookup estimates, which explain why Memoize was chosen.
- JIT is disabled by default; the `JIT:` block disappears unless a site enables `jit` for analytical queries.

## Sources

- EXPLAIN: <https://www.postgresql.org/docs/18/sql-explain.html> (checked 2026-10-27)
- Using EXPLAIN: <https://www.postgresql.org/docs/18/using-explain.html> (checked 2026-10-27)
- PostgreSQL 18 release notes, E.6.3.2.3 EXPLAIN: <https://www.postgresql.org/docs/18/release-18.html> (checked 2026-10-27)
- PostgreSQL 17 release notes (SERIALIZE, MEMORY): <https://www.postgresql.org/docs/17/release-17.html> (checked 2026-10-27)
- PostgreSQL 16 release notes (GENERIC_PLAN): <https://www.postgresql.org/docs/16/release-16.html> (checked 2026-10-27)
- Resource Consumption, `work_mem`, `hash_mem_multiplier`: <https://www.postgresql.org/docs/18/runtime-config-resource.html> (checked 2026-10-27)
- Query Planning settings, `plan_cache_mode`, `jit`, `jit_above_cost`: <https://www.postgresql.org/docs/18/runtime-config-query.html> (checked 2026-10-27)
- JIT decision: <https://www.postgresql.org/docs/18/jit-decision.html> (checked 2026-10-27)
- PREPARE: <https://www.postgresql.org/docs/18/sql-prepare.html> (checked 2026-10-27)
- pg_prepared_statements: <https://www.postgresql.org/docs/18/view-pg-prepared-statements.html> (checked 2026-10-27)
- How Parallel Query Works: <https://www.postgresql.org/docs/18/how-parallel-query-works.html>; Parallel Plans: <https://www.postgresql.org/docs/18/parallel-plans.html> (checked 2026-10-27)
- Routine Vacuuming, visibility map: <https://www.postgresql.org/docs/18/routine-vacuuming.html> (checked 2026-10-27)
- PostgreSQL 18 source, `explain.c` (which counters are per loop, which are totals): <https://github.com/postgres/postgres/blob/REL_18_STABLE/src/backend/commands/explain.c> (checked 2026-10-27)
- pgx v5 package docs (`ConnConfig`, `default_query_exec_mode`): <https://pkg.go.dev/github.com/jackc/pgx/v5> (checked 2026-10-27)
- PostgreSQL 19 release notes, as of 2026-10-09: <https://www.postgresql.org/docs/19/release-19.html> (checked 2026-10-27)
