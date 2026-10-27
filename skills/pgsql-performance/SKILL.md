---
name: pgsql-performance
description: PostgreSQL query performance, diagnosis and analysis on PostgreSQL 18 (19 additions flagged as hints). This skill should be used when a query or a database is slow, when reading or producing EXPLAIN or EXPLAIN ANALYZE output (estimated versus actual rows, loops, Buffers, Rows Removed by Filter, sorts or hashes spilling to disk, Index Searches, JIT, parallel workers), when planner estimates are wrong (ANALYZE, pg_stats, CREATE STATISTICS, SET STATISTICS), when a query is fast in psql but slow as a prepared statement from pgx or PDO (generic plans, plan_cache_mode), for pg_stat_statements, auto_explain, pg_stat_activity, wait events, lock waits, pg_blocking_pids, idle in transaction sessions, timeouts, autovacuum and bloat, or when deciding whether a plan justifies rewriting NOT IN, OFFSET paging, COUNT(*), OR, a CTE or a correlated subquery. Not for choosing an index (pgsql-indexing), writing the query (pgsql-query), jsonb operators (pgsql-jsonb) or migration locks (pgsql-migrations).
---

# pgsql-performance: diagnose and tune PostgreSQL queries

Scope: find out why a statement or a workload is slow, read the evidence, and decide the fix. Index design belongs to `pgsql-indexing`, query idioms to `pgsql-query`, jsonb predicates to `pgsql-jsonb`.

Deterministic backstop: `EXPLAIN (ANALYZE, BUFFERS)` for one statement, `pg_stat_statements` for the workload, `pg_stat_activity` with `pg_blocking_pids()` for waits. The plan decides; this skill is how to read it.

## Rules

- **Get a plan before proposing a fix.** No index, rewrite or setting change without `EXPLAIN (ANALYZE, BUFFERS)` output, and the same command again after the change. A plan from a toy-sized table "cannot be assumed to apply to large tables" ([Using EXPLAIN](https://www.postgresql.org/docs/18/using-explain.html)); say how much data the plan ran on.
- **`EXPLAIN ANALYZE` runs the statement.** Side effects happen as usual. Wrap `INSERT`, `UPDATE`, `DELETE` or `MERGE` in `BEGIN; ... ROLLBACK;`, and ask before running it on a shared or production database ([EXPLAIN](https://www.postgresql.org/docs/18/sql-explain.html)).
- **Compare estimated and actual rows first.** The manual calls this "usually most important" ([Using EXPLAIN](https://www.postgresql.org/docs/18/using-explain.html)). Multiply actual rows and time by `loops`. Start from the lowest node whose estimate is far off: every node above it was planned for the wrong row count.
- **Fix a misestimate at its cause, not with `enable_*`.** Stale statistics need `ANALYZE`; a skewed column needs `ALTER TABLE ... SET STATISTICS`; correlated columns need `CREATE STATISTICS` and then `ANALYZE`. The `enable_*` settings are "a crude method" and a "temporary solution" ([Planner Method Configuration](https://www.postgresql.org/docs/18/runtime-config-query.html)). Use them to explore, never as the fix.
- **Read `Buffers` as I/O.** `hit` was in shared buffers, `read` was not. PostgreSQL 18 includes buffers automatically with `ANALYZE` ([release notes 18](https://www.postgresql.org/docs/18/release-18.html)). Turn on `track_io_timing` to see read time.
- **A disk sort or `Batches` above 1 means `work_mem` was too small for that node.** `work_mem` applies per sort or hash operation, and several run at once across sessions ([Resource Consumption](https://www.postgresql.org/docs/18/runtime-config-resource.html)). Raise it with `SET LOCAL` for the query that needs it, not globally.
- **A query fast in `psql` and slow from the application may be running a generic plan.** pgx prepares and caches statements by default ([pgx](https://pkg.go.dev/github.com/jackc/pgx/v5)); after five custom-planned executions the server may switch to a generic plan, which cannot use the parameter's value ([PREPARE](https://www.postgresql.org/docs/18/sql-prepare.html)). Reproduce it with `EXPLAIN (GENERIC_PLAN)` or `EXPLAIN EXECUTE`, and set `plan_cache_mode = force_custom_plan` only where the generic plan is measurably worse ([explain.md](references/explain.md)). The driver's exec modes are in `pgsql-query`.
- **Find the workload's worst statements before tuning one.** Sort `pg_stat_statements` by `total_exec_time` for load and `mean_exec_time` for latency ([pg_stat_statements](https://www.postgresql.org/docs/18/pgstatstatements.html)).
- **Keep `auto_explain.log_analyze` off in production.** It times every statement, logged or not, with "an extremely negative impact on performance" ([auto_explain](https://www.postgresql.org/docs/18/auto-explain.html)). Use it with sampling on staging.
- **Waiting is not running.** A session with `wait_event_type = 'Lock'` is blocked; `pg_blocking_pids(pid)` names the blockers ([pg_locks](https://www.postgresql.org/docs/18/view-pg-locks.html)). A session `idle in transaction` holds its locks and stops vacuum from removing dead rows ([Client Connection Defaults](https://www.postgresql.org/docs/18/runtime-config-client.html)).
- **Set timeouts per role, session or transaction.** `statement_timeout`, `lock_timeout` and `transaction_timeout` in `postgresql.conf` are "not recommended because it would affect all sessions" ([Client Connection Defaults](https://www.postgresql.org/docs/18/runtime-config-client.html)).
- **Check JIT on short queries.** A `JIT:` block whose `Total` is a large share of `Execution Time` is overhead; "for short queries the added overhead of performing JIT compilation will often be higher than the time it can save" ([JIT decision](https://www.postgresql.org/docs/18/jit-decision.html)).
- **Rewrite only what the plan points at, and prove the rows are the same.** Each rewrite in [rewrites.md](references/rewrites.md) names the plan evidence that justifies it.

## Summarise a plan before reading it

- **Run the summariser first.** `python3 <this skill's base directory>/scripts/plan-summary.py plan.txt` (or `-` for stdin) reads TEXT or JSON plans, psql's aligned output included, and prints the totals, the nodes with the most exclusive time, and mechanical findings: the node where a row-estimate error starts and where it grows, sorts and hashes that spilled, nodes run thousands of times, filters that discard most rows, heap fetches, unlaunched workers, and JIT share. It is arithmetic on the plan, not a diagnosis; read the flagged lines and apply the rules above.
- **Hand a long plan to `pgsql-plan-analyst`.** For a plan over about 50 lines, two plans to compare, or an analysis that would fill the conversation, write the plan to a scratch file and dispatch the agent with its path, the query, and the database it may query, if any. It returns a ranked diagnosis with the command that confirms each fix.

## Read the reference

| The task involves | Read |
|---|---|
| A plan to read or produce: EXPLAIN options, loops, buffers, sorts and hashes, Index Searches, parallel workers, JIT, a statement slow only as a prepared statement | [explain.md](references/explain.md) |
| Estimates far from actual rows, `ANALYZE`, `pg_stats`, `CREATE STATISTICS`, statistics targets, `n_distinct` | [statistics.md](references/statistics.md) |
| Finding slow statements in a workload, `auto_explain`, slow-query logging, sessions waiting, locks, timeouts, autovacuum and bloat, connection counts | [diagnostics.md](references/diagnostics.md) |
| Deciding whether to rewrite `NOT IN`, a function or cast on a filtered column, `OFFSET` paging, `COUNT(*)`, `OR` across columns, a CTE, a per-row SubPlan | [rewrites.md](references/rewrites.md) |

## Sources

- PostgreSQL 18 manual: [Using EXPLAIN](https://www.postgresql.org/docs/18/using-explain.html), [EXPLAIN](https://www.postgresql.org/docs/18/sql-explain.html), [Statistics Used by the Planner](https://www.postgresql.org/docs/18/planner-stats.html), [Query Planning settings](https://www.postgresql.org/docs/18/runtime-config-query.html), [Resource Consumption](https://www.postgresql.org/docs/18/runtime-config-resource.html), [Client Connection Defaults](https://www.postgresql.org/docs/18/runtime-config-client.html), [PREPARE](https://www.postgresql.org/docs/18/sql-prepare.html), [pg_stat_statements](https://www.postgresql.org/docs/18/pgstatstatements.html), [auto_explain](https://www.postgresql.org/docs/18/auto-explain.html), [pg_locks](https://www.postgresql.org/docs/18/view-pg-locks.html), [JIT decision](https://www.postgresql.org/docs/18/jit-decision.html)
- [PostgreSQL 18 release notes](https://www.postgresql.org/docs/18/release-18.html); [PostgreSQL 19 release notes](https://www.postgresql.org/docs/19/release-19.html) (hints only)
- pgx v5 `ConnConfig.DefaultQueryExecMode`: <https://pkg.go.dev/github.com/jackc/pgx/v5>
