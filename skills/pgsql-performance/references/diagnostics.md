# Workload diagnostics

Read when: the slow statement is not known yet; latency spikes or sessions pile up; a statement waits instead of running; `idle in transaction` sessions appear; a table grows while its row count does not; or a repository sets up `pg_stat_statements`, `auto_explain`, slow-query logging or timeouts.

Backstop: `pg_stat_statements` for the workload, `pg_stat_activity` with `pg_blocking_pids()` for waits, `pg_stat_user_tables` for vacuum and analyze.

## Contents

- Find the expensive statements
- Capture plans and slow statements in the log
- Sessions, waits and locks
- Timeouts
- Dead rows, vacuum and bloat
- Connections
- Newer in PostgreSQL 19 (hints)
- Sources

## Find the expensive statements

- **Install `pg_stat_statements` once per server.** Add it to `shared_preload_libraries` (restart required), keep `compute_query_id` at `auto` or `on`, and run `CREATE EXTENSION pg_stat_statements` in each database ([pg_stat_statements](https://www.postgresql.org/docs/18/pgstatstatements.html)).
- **Sort by the question being asked** ([pg_stat_statements](https://www.postgresql.org/docs/18/pgstatstatements.html)):
  - `total_exec_time`: where the server spends its time overall.
  - `mean_exec_time` with `calls`: which statement is slow per call.
  - `shared_blks_read` and `shared_blk_read_time`: I/O; the time column stays zero unless `track_io_timing` is on.
  - `temp_blks_written`: sorts and hashes spilling past `work_mem`.
  - `rows / calls`: a statement that returns far more rows than the caller uses.

```sql
SELECT queryid, calls, round(total_exec_time) AS total_ms, round(mean_exec_time, 2) AS mean_ms,
       rows, shared_blks_read, temp_blks_written,
       100.0 * shared_blks_hit / nullif(shared_blks_hit + shared_blks_read, 0) AS hit_percent,
       left(query, 120) AS query
FROM pg_stat_statements
ORDER BY total_exec_time DESC
LIMIT 10;
```

- **One row per statement shape.** Statements that differ only in literal constants share a `queryid` and show `$1` in place of the constant; lists of constants are squashed to `IN ($1 /*, ... */)` ([pg_stat_statements](https://www.postgresql.org/docs/18/pgstatstatements.html)). Use `queryid` to follow one statement across resets.
- **Measure a fix against a clean baseline.** `pg_stat_statements_reset(0, 0, queryid)` resets one statement; `(0, 0, 0)` resets all, and needs a superuser or a granted role ([pg_stat_statements](https://www.postgresql.org/docs/18/pgstatstatements.html)).
- **Know the defaults.** `pg_stat_statements.max` is 5000 statements, dropping the least executed; `pg_stat_statements.track_planning` is `off` because it "may incur a noticeable performance penalty" ([pg_stat_statements](https://www.postgresql.org/docs/18/pgstatstatements.html)).

## Capture plans and slow statements in the log

- **`auto_explain` logs the plans of slow statements.** Preload it with `session_preload_libraries` or `LOAD 'auto_explain'` (superuser), and set `auto_explain.log_min_duration`; its default `-1` logs nothing ([auto_explain](https://www.postgresql.org/docs/18/auto-explain.html)).
- **`auto_explain.log_analyze` costs every statement.** Timing happens for all statements "whether or not they run long enough to actually get logged" with "an extremely negative impact on performance"; `log_timing = off` keeps row counts at lower cost, and `sample_rate` explains only a fraction of statements ([auto_explain](https://www.postgresql.org/docs/18/auto-explain.html)). `log_buffers` requires `log_analyze`; `log_nested_statements` adds statements run inside functions. A staging recipe:

```ini
session_preload_libraries = 'auto_explain'
auto_explain.log_min_duration = '250ms'
auto_explain.log_analyze = on
auto_explain.log_buffers = on
auto_explain.log_timing = off
auto_explain.sample_rate = 0.1
auto_explain.log_format = 'json'
```

- **Log durations without plans with `log_min_duration_statement`** (default `-1`, off), or sample them with `log_min_duration_sample` and `log_statement_sample_rate`. With the extended query protocol, as pgx and PDO use, Parse, Bind and Execute durations are logged separately ([Error Reporting and Logging](https://www.postgresql.org/docs/18/runtime-config-logging.html)).
- **Log spills with `log_temp_files = 0`.** It logs every temporary file a sort, hash or temporary result creates, with its size ([Error Reporting and Logging](https://www.postgresql.org/docs/18/runtime-config-logging.html)).

## Sessions, waits and locks

- **Read `state` and `wait_event_type` together** ([Cumulative Statistics](https://www.postgresql.org/docs/18/monitoring-stats.html)). `Lock` is a heavyweight lock wait; `LWLock` a lightweight lock; `IO` an I/O wait; `Client` means the server waits on the application socket, so the delay is outside the database; `idle in transaction` means a transaction is open and no statement runs.
- **Find blockers with `pg_blocking_pids()`, not a self-join of `pg_locks`.** The self-join "is very difficult to get right in detail" ([pg_locks](https://www.postgresql.org/docs/18/view-pg-locks.html)). The function returns hard and soft blockers; frequent calls take the lock manager's state exclusively for a moment, so do not poll it in a tight loop ([System Information Functions](https://www.postgresql.org/docs/18/functions-info.html)).

```sql
SELECT a.pid, pg_blocking_pids(a.pid) AS blocked_by, a.wait_event_type, a.wait_event,
       a.state, now() - a.xact_start AS xact_age, left(a.query, 80) AS query
FROM pg_stat_activity AS a
WHERE cardinality(pg_blocking_pids(a.pid)) > 0;
```

- **Log lock waits.** `log_lock_waits` (default `off` in 18) logs any wait longer than `deadlock_timeout` (default `1s`); lower `deadlock_timeout` while investigating ([Error Reporting and Logging](https://www.postgresql.org/docs/18/runtime-config-logging.html), [Lock Management](https://www.postgresql.org/docs/18/runtime-config-locks.html)).
- **Find long transactions.** Old `xact_start` values and a large `age(backend_xmin)` in `pg_stat_activity` mark the transactions to end first ([Routine Vacuuming](https://www.postgresql.org/docs/18/routine-vacuuming.html)).

## Timeouts

Set these per role, per session or with `SET LOCAL`; for `statement_timeout`, `lock_timeout` and `transaction_timeout`, setting them in `postgresql.conf` "is not recommended because it would affect all sessions" ([Client Connection Defaults](https://www.postgresql.org/docs/18/runtime-config-client.html)). All default to `0`, disabled.

- **`statement_timeout`** aborts a statement that runs too long. With the extended protocol it starts when a Parse, Bind, Execute or Describe message arrives.
- **`lock_timeout`** aborts a statement that waits too long for any single lock. It is pointless at or above `statement_timeout`.
- **`transaction_timeout`** (PG 17) ends a session whose transaction runs too long.
- **`idle_in_transaction_session_timeout`** ends a session idle inside a transaction. An open transaction holds its locks and "prevents vacuuming away recently-dead tuples", so it causes bloat.
- **`idle_session_timeout`** is risky behind a connection pool, which may not handle the closed connection.

## Dead rows, vacuum and bloat

- **`UPDATE` and `DELETE` leave dead row versions.** Plain `VACUUM` makes their space reusable but rarely returns it to the operating system; `VACUUM FULL` rewrites the table under an `ACCESS EXCLUSIVE` lock, so avoid it on a live table ([Routine Vacuuming](https://www.postgresql.org/docs/18/routine-vacuuming.html)). Schedule a table rewrite through `pgsql-migrations`.
- **Know when autovacuum fires.** By default once dead rows exceed 50 plus 20 percent of the table, capped at 100,000,000; every threshold can be overridden per table with a storage parameter ([Routine Vacuuming](https://www.postgresql.org/docs/18/routine-vacuuming.html), [Vacuuming settings](https://www.postgresql.org/docs/18/runtime-config-vacuum.html)).
- **Check dead rows and vacuum activity.** Compare `n_dead_tup` with `n_live_tup` and read `last_autovacuum` in `pg_stat_user_tables` ([Cumulative Statistics](https://www.postgresql.org/docs/18/monitoring-stats.html)). PostgreSQL 18 adds `total_vacuum_time`, `total_autovacuum_time`, `total_analyze_time` and `total_autoanalyze_time` ([release notes 18](https://www.postgresql.org/docs/18/release-18.html)). `log_autovacuum_min_duration` (default `10min`) logs slow autovacuum runs and skipped ones ([Error Reporting and Logging](https://www.postgresql.org/docs/18/runtime-config-logging.html)).
- **Dead rows a long transaction can still see are not removed.** An open transaction "prevents vacuuming away recently-dead tuples that may be visible only to this transaction" ([Client Connection Defaults](https://www.postgresql.org/docs/18/runtime-config-client.html)). Fix the transaction (timeouts above) before tuning autovacuum.

## Connections

- **Count `work_mem` per operation and per session.** Total memory "could be many times the value of `work_mem`" because one query runs several sorts and hashes and many sessions run at once ([Resource Consumption](https://www.postgresql.org/docs/18/runtime-config-resource.html)). Many active connections multiply it.
- **Fewer active connections can mean more throughput.** The PostgreSQL wiki attributes the drop past a point to contention for disk, memory, locks and CPU, and recommends a connection pool ([Number Of Database Connections](https://wiki.postgresql.org/wiki/Number_Of_Database_Connections), last edited 2014). Size the pool from measurement; pool settings for pgx and PDO are in `pgsql-query`.

## Newer in PostgreSQL 19 (hints)

Release candidate only ([release notes 19](https://www.postgresql.org/docs/19/release-19.html)):

- `log_lock_waits` is on by default.
- `pg_stat_statements` groups `FETCH` statements of different sizes and counts generic and custom plans.
- Autovacuum can use parallel workers (`autovacuum_max_parallel_workers`, per-table `autovacuum_parallel_workers`) and orders tables by a score.

## Sources

- pg_stat_statements: <https://www.postgresql.org/docs/18/pgstatstatements.html> (checked 2026-10-27)
- auto_explain: <https://www.postgresql.org/docs/18/auto-explain.html> (checked 2026-10-27)
- Error Reporting and Logging: <https://www.postgresql.org/docs/18/runtime-config-logging.html> (checked 2026-10-27)
- Cumulative Statistics, `pg_stat_activity`, wait event types, `pg_stat_all_tables`: <https://www.postgresql.org/docs/18/monitoring-stats.html> (checked 2026-10-27)
- pg_locks: <https://www.postgresql.org/docs/18/view-pg-locks.html> (checked 2026-10-27)
- System Information Functions, `pg_blocking_pids`: <https://www.postgresql.org/docs/18/functions-info.html> (checked 2026-10-27)
- Lock Management, `deadlock_timeout`: <https://www.postgresql.org/docs/18/runtime-config-locks.html> (checked 2026-10-27)
- Client Connection Defaults, timeouts: <https://www.postgresql.org/docs/18/runtime-config-client.html> (checked 2026-10-27)
- Routine Vacuuming: <https://www.postgresql.org/docs/18/routine-vacuuming.html> (checked 2026-10-27)
- Vacuuming settings: <https://www.postgresql.org/docs/18/runtime-config-vacuum.html> (checked 2026-10-27)
- Resource Consumption, `work_mem`: <https://www.postgresql.org/docs/18/runtime-config-resource.html> (checked 2026-10-27)
- PostgreSQL 18 release notes: <https://www.postgresql.org/docs/18/release-18.html> (checked 2026-10-27)
- PostgreSQL wiki, Number Of Database Connections: <https://wiki.postgresql.org/wiki/Number_Of_Database_Connections> (checked 2026-10-27)
- PostgreSQL 19 release notes, as of 2026-10-09: <https://www.postgresql.org/docs/19/release-19.html> (checked 2026-10-27)
