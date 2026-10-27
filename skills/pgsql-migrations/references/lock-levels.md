# Lock levels, the lock queue and timeouts

Read when: a migration takes or waits for a table lock, a deploy stalled traffic, a file needs `lock_timeout` or `statement_timeout`, or the question is which lock an `ALTER TABLE`, index or constraint statement takes.

Backstop: squawk `require-lock-timeout` and `require-statement-timeout` flag a file whose slow DDL comes before a `SET` of each. No tool reports which lock a statement takes; the table below does.

## Contents

- What each statement locks
- The lock queue
- Timeouts
- A migration waiting right now
- Newer in PostgreSQL 19 (hints)

## Rules

### What each statement locks

- **`ALTER TABLE` takes `ACCESS EXCLUSIVE` unless its page says otherwise.** With several subcommands in one statement, it takes the strongest lock any of them needs ([ALTER TABLE](https://www.postgresql.org/docs/18/sql-altertable.html)).
- **Only `ACCESS EXCLUSIVE` blocks a plain `SELECT`** ([13.3.1](https://www.postgresql.org/docs/18/explicit-locking.html#LOCKING-TABLES)). Every lock in the table below blocks something a live application does.

| Lock | Blocks | Taken by |
|---|---|---|
| `ACCESS EXCLUSIVE` | every read and write | most `ALTER TABLE` forms (`ADD COLUMN`, `DROP COLUMN`, `RENAME`, `SET NOT NULL`, `SET DATA TYPE`, `ADD CONSTRAINT` other than a foreign key, `ADD ... USING INDEX`), `DROP TABLE`, `TRUNCATE`, `VACUUM FULL`, `CLUSTER`, plain `DROP INDEX`, `REFRESH MATERIALIZED VIEW` |
| `SHARE ROW EXCLUSIVE` | writes and other DDL | `ADD FOREIGN KEY`, on both tables; `CREATE TRIGGER`; `ENABLE` or `DISABLE TRIGGER` |
| `SHARE` | writes | `CREATE INDEX` without `CONCURRENTLY` |
| `SHARE UPDATE EXCLUSIVE` | other DDL and `VACUUM`, not reads or writes | `CREATE INDEX CONCURRENTLY`, `REINDEX CONCURRENTLY`, `VALIDATE CONSTRAINT`, `SET STATISTICS`, storage parameters, `VACUUM`, `ANALYZE` |

- **`REINDEX` without `CONCURRENTLY` blocks writes to the table** and takes `ACCESS EXCLUSIVE` on the index, which blocks reads that would use it ([REINDEX](https://www.postgresql.org/docs/18/sql-reindex.html)).
- **`VALIDATE CONSTRAINT` on a foreign key also takes `ROW SHARE` on the referenced table** ([ALTER TABLE notes](https://www.postgresql.org/docs/18/sql-altertable.html#SQL-ALTERTABLE-NOTES)).

### The lock queue

- **A waiting statement blocks the requests behind it.** `pg_blocking_pids` counts as a blocker any session that "is waiting for a lock that would conflict with the blocked process's lock request and is ahead of it in the wait queue" ([`pg_blocking_pids`](https://www.postgresql.org/docs/18/functions-info.html#FUNCTIONS-INFO-SESSION-TABLE)). An `ALTER TABLE` waiting for `ACCESS EXCLUSIVE` behind one long transaction holds up every later query on that table until it gets the lock ([squawk](https://squawkhq.com/docs/safe_migrations)).
- **By default a lock wait never ends.** A transaction "will wait indefinitely for conflicting locks to be released" unless a deadlock is detected ([13.3.4](https://www.postgresql.org/docs/18/explicit-locking.html#LOCKING-DEADLOCKS)). `lock_timeout` and `statement_timeout` default to 0, which disables them ([client settings](https://www.postgresql.org/docs/18/runtime-config-client.html#GUC-LOCK-TIMEOUT)).
- **Locks last until the transaction ends.** Table locks and row locks are released at commit or rollback ([13.3.1](https://www.postgresql.org/docs/18/explicit-locking.html#LOCKING-TABLES), [13.3.2](https://www.postgresql.org/docs/18/explicit-locking.html#LOCKING-ROWS)). A quick `ACCESS EXCLUSIVE` step keeps blocking for as long as the slowest later statement in its transaction runs.
- **A session idle inside a transaction is a common blocker.** `idle_in_transaction_session_timeout` ends such sessions; the manual names it as the way "to ensure that idle sessions do not hold locks for an unreasonable amount of time" ([client settings](https://www.postgresql.org/docs/18/runtime-config-client.html#GUC-IDLE-IN-TRANSACTION-SESSION-TIMEOUT)).

### Timeouts

- **Set both timeouts at the top of every migration file whose DDL takes `ACCESS EXCLUSIVE`, `SHARE ROW EXCLUSIVE` or `SHARE`.** squawk requires both and suggests these values ([squawk](https://squawkhq.com/docs/safe_migrations)); a file of concurrent index statements is the exception below:

```sql
SET lock_timeout = '1s';
SET statement_timeout = '5s';
```

- **`lock_timeout` applies to each lock attempt separately.** A `lock_timeout` equal to or above `statement_timeout` is pointless, because the statement timeout fires first ([client settings](https://www.postgresql.org/docs/18/runtime-config-client.html#GUC-LOCK-TIMEOUT)).
- **On a lock timeout, rerun the migration; do not raise the timeout.** The timeout let waiting queries through, which is its purpose ([squawk](https://squawkhq.com/docs/safe_migrations)).
- **Switch both timeouts off for `CREATE INDEX CONCURRENTLY`, `REINDEX ... CONCURRENTLY` and `DROP INDEX CONCURRENTLY`:** `SET lock_timeout = 0;` and `SET statement_timeout = 0;` (or a generous bound) in a file of its own. A concurrent build waits for every older transaction that modified the table, and after its second scan for every transaction whose snapshot predates it ([CREATE INDEX](https://www.postgresql.org/docs/18/sql-createindex.html#SQL-CREATEINDEX-CONCURRENTLY)); `DROP INDEX CONCURRENTLY` also waits for conflicting transactions ([DROP INDEX](https://www.postgresql.org/docs/18/sql-dropindex.html)). `lock_timeout` aborts a statement waiting for a lock "on a table, index, row, or other database object" ([client settings](https://www.postgresql.org/docs/18/runtime-config-client.html#GUC-LOCK-TIMEOUT)), so on a busy system a short value cancels the build and leaves an `INVALID` index. Waiting costs little: the build's `SHARE UPDATE EXCLUSIVE` lock does not conflict with the `ROW EXCLUSIVE` lock that `INSERT`, `UPDATE` and `DELETE` take ([13.3.1](https://www.postgresql.org/docs/18/explicit-locking.html#LOCKING-TABLES)), and while it waits for an older transaction (`wait_event` `virtualxid`) writes to the table proceed (checked on 18.6). squawk expects such files to need different values ([squawk](https://squawkhq.com/docs/safe_migrations)).
- **Do not set either in `postgresql.conf`.** The manual says this "is not recommended because it would affect all sessions" ([client settings](https://www.postgresql.org/docs/18/runtime-config-client.html#GUC-STATEMENT-TIMEOUT)). Set them in the migration file, on the migration role, or in the connection options ([squawk](https://squawkhq.com/docs/safe_migrations)).
- **`SET` outlives its transaction; `SET LOCAL` does not.** Once its transaction commits, a plain `SET` stays in force for the rest of the session. `SET LOCAL` ends with the transaction, and outside a transaction block it only emits a warning ([SET](https://www.postgresql.org/docs/18/sql-set.html)). A value set by one file can therefore still apply to the next file run on the same connection, so each file sets its own.

### A migration waiting right now

List who blocks whom:

```sql
SELECT pid, pg_blocking_pids(pid) AS blocked_by, wait_event_type, state, xact_start, query
FROM pg_stat_activity
WHERE cardinality(pg_blocking_pids(pid)) > 0;
```

- **Do not poll it in a tight loop.** Each call needs exclusive access to the lock manager's shared state for a short time ([`pg_blocking_pids`](https://www.postgresql.org/docs/18/functions-info.html#FUNCTIONS-INFO-SESSION-TABLE)). Columns: [`pg_stat_activity`](https://www.postgresql.org/docs/18/monitoring-stats.html#MONITORING-PG-STAT-ACTIVITY-VIEW).
- **Let the migration give way, then rerun it.** A lock timeout cancels the migration and lets the queued queries proceed ([squawk](https://squawkhq.com/docs/safe_migrations)); ending the blocking session is the user's decision. Lock-wait analysis outside a migration belongs to `pgsql-performance`.

## Newer in PostgreSQL 19 (hints)

These apply once the server runs PostgreSQL 19 ([release notes 19](https://www.postgresql.org/docs/19/release-19.html), as of 2026-10-09):

- **`log_lock_waits` is on by default,** so a migration stuck behind a lock shows up in the server log.
- **`max_locks_per_transaction` defaults to 128 instead of 64,** and lock memory is sized differently: an existing setting must be doubled to keep its old capacity.
- **`REPACK (CONCURRENTLY)` rebuilds a table without `ACCESS EXCLUSIVE`,** replacing `VACUUM FULL` and `CLUSTER`, which remain for compatibility. squawk `prefer-repack` fires only when its `pg_version` is 19 or higher.
- **`ALTER TABLE ... ALTER CONSTRAINT ... [NOT] ENFORCED` works on `CHECK` constraints,** not only foreign keys.

## Sources

- PostgreSQL 18, explicit locking (13.3.1 table locks, 13.3.2 row locks, 13.3.4 deadlocks): <https://www.postgresql.org/docs/18/explicit-locking.html> (checked 2026-10-27)
- PostgreSQL 18, ALTER TABLE (lock per subform, notes): <https://www.postgresql.org/docs/18/sql-altertable.html> (checked 2026-10-27)
- PostgreSQL 18, REINDEX: <https://www.postgresql.org/docs/18/sql-reindex.html> (checked 2026-10-27)
- PostgreSQL 18, CREATE INDEX, building indexes concurrently: <https://www.postgresql.org/docs/18/sql-createindex.html> (checked 2026-10-27)
- PostgreSQL 18, client connection defaults (`lock_timeout`, `statement_timeout`, `idle_in_transaction_session_timeout`): <https://www.postgresql.org/docs/18/runtime-config-client.html> (checked 2026-10-27)
- PostgreSQL 18, SET: <https://www.postgresql.org/docs/18/sql-set.html> (checked 2026-10-27)
- PostgreSQL 18, `pg_blocking_pids`: <https://www.postgresql.org/docs/18/functions-info.html> (checked 2026-10-27)
- PostgreSQL 18, `pg_stat_activity`: <https://www.postgresql.org/docs/18/monitoring-stats.html> (checked 2026-10-27)
- squawk, applying migrations safely: <https://squawkhq.com/docs/safe_migrations> (checked 2026-10-27)
- PostgreSQL 19 release notes, as of 2026-10-09: <https://www.postgresql.org/docs/19/release-19.html> (checked 2026-10-27)
