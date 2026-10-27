# Transactions, locking and retries

Read when: code sets an isolation level, reads a value and writes it back, handles SQLSTATE `40001`, `40P01` or `23505`, uses `SELECT ... FOR UPDATE`, `FOR SHARE`, `NOWAIT` or `SKIP LOCKED`, builds a job queue, calls `pg_advisory_lock` or `pg_advisory_xact_lock`, or holds a transaction open across slow work.

Deterministic backstop: none for the logic. Lock waits show up in `pg_stat_activity` and `pg_locks`, which `pgsql-performance` reads. Reproduce a race with two connections in a test (see `testing.md`).

## Isolation levels

- **Read Committed is the default, and each statement sees a fresh snapshot.** An `UPDATE` that waits on a concurrent writer re-checks its `WHERE` against the new row version and proceeds. That is safe for a single-row change such as `SET balance = balance + 100`. The manual calls the mode "unsuitable for commands that involve complex search conditions" ([Read Committed](https://www.postgresql.org/docs/18/transaction-iso.html#XACT-READ-COMMITTED)).
- **Do not read a value in one statement and write it back from the application in another.** Under Read Committed a concurrent change in between is lost. Write it as one statement (`SET qty = qty - $1 WHERE qty >= $1`), or lock the row first with `SELECT ... FOR UPDATE` ([locking clause](https://www.postgresql.org/docs/18/sql-select.html#SQL-FOR-UPDATE-SHARE)).
- **Repeatable Read and Serializable raise a serialization failure where Read Committed would carry on, so retry them.** The error is SQLSTATE `40001`. Abort and "retry the whole transaction from the beginning", including the reads, since results read in an aborted transaction must not be trusted ([Repeatable Read](https://www.postgresql.org/docs/18/transaction-iso.html#XACT-REPEATABLE-READ), [Serializable](https://www.postgresql.org/docs/18/transaction-iso.html#XACT-SERIALIZABLE)).
- **Declare Serializable transactions `READ ONLY` when they do not write.** The manual lists it first for good Serializable performance ([Serializable](https://www.postgresql.org/docs/18/transaction-iso.html#XACT-SERIALIZABLE)). `SERIALIZABLE READ ONLY DEFERRABLE` may block while taking its snapshot, then runs with no risk of a serialization failure; the manual suggests it for long reports and backups ([SET TRANSACTION](https://www.postgresql.org/docs/18/sql-set-transaction.html)).

## Errors to branch on

- **Branch on the SQLSTATE code, never on the message text.** Codes are stable across releases and locales ([error codes](https://www.postgresql.org/docs/18/errcodes-appendix.html)).

| Code | Name | Typical response |
|---|---|---|
| `40001` | `serialization_failure` | retry the whole transaction |
| `40P01` | `deadlock_detected` | this transaction was the aborted victim; retry it and fix the lock order |
| `23505` | `unique_violation` | report a conflict, or switch to `ON CONFLICT` |
| `23503` | `foreign_key_violation` | report the missing parent |
| `23514` | `check_violation` | report the failed rule |
| `23P01` | `exclusion_violation` | report the overlap |
| `55P03` | `lock_not_available` | `NOWAIT` or `lock_timeout` gave up |
| `57014` | `query_canceled` | a timeout or a cancel request ended the statement |
| `21000` | `cardinality_violation` | duplicate keys in one upsert or `MERGE` |

- **A deadlock aborts one of the transactions involved** so the others can finish; which one is unpredictable ([deadlocks](https://www.postgresql.org/docs/18/explicit-locking.html#LOCKING-DEADLOCKS)). The driver-side retry loop is in `go-pgx.md` and `php-pdo.md`.

## Row locks and queues

- **Claim queue rows with `FOR UPDATE SKIP LOCKED`.** Rows another session holds are skipped instead of waited on. The view is inconsistent, so use it only for queue-like tables, never for general reads ([locking clause](https://www.postgresql.org/docs/18/sql-select.html#SQL-FOR-UPDATE-SHARE)).
- **Use `NOWAIT` to fail fast instead of waiting.** It raises an error when a row cannot be locked at once ([locking clause](https://www.postgresql.org/docs/18/sql-select.html#SQL-FOR-UPDATE-SHARE)).
- **Put `LIMIT` in the locking query, not `OFFSET`.** With `LIMIT`, locking stops once enough rows are returned, but rows skipped by `OFFSET` are still locked ([locking clause](https://www.postgresql.org/docs/18/sql-select.html#SQL-FOR-UPDATE-SHARE)).

```sql
WITH next AS (
  SELECT id FROM jobs
  WHERE state = 'queued'
  ORDER BY id
  LIMIT 10
  FOR UPDATE SKIP LOCKED
)
UPDATE jobs j SET state = 'running', started_at = now()
FROM next
WHERE j.id = next.id
RETURNING j.id, j.payload;
```

## Deadlocks and transaction length

- **Lock rows in one consistent order everywhere,** for example by ascending primary key. Take the most restrictive lock mode the transaction will need first ([deadlocks](https://www.postgresql.org/docs/18/explicit-locking.html#LOCKING-DEADLOCKS)).
- **Keep a transaction to the work integrity needs.** A lock waiter waits indefinitely, so a transaction held open for user input, a remote call or a long loop blocks others. Do not leave a connection "idle in transaction" longer than necessary ([deadlocks](https://www.postgresql.org/docs/18/explicit-locking.html#LOCKING-DEADLOCKS), [Serializable](https://www.postgresql.org/docs/18/transaction-iso.html#XACT-SERIALIZABLE)).

## Advisory locks

- **Prefer `pg_advisory_xact_lock` and `pg_try_advisory_xact_lock`.** They release at transaction end ([advisory lock functions](https://www.postgresql.org/docs/18/functions-admin.html#FUNCTIONS-ADVISORY-LOCKS)). A session-level lock ignores transaction semantics: it survives a rollback and lasts until unlock or session end ([advisory locks](https://www.postgresql.org/docs/18/explicit-locking.html#ADVISORY-LOCKS)). On a pooled connection the session outlives the request.
- **Never call a lock function in the same query level as `LIMIT`.** The limit is not guaranteed to apply before the function runs, so extra locks are taken. Apply the limit in a subquery ([advisory locks](https://www.postgresql.org/docs/18/explicit-locking.html#ADVISORY-LOCKS)).

```sql
-- 4201: an application-wide constant reserved for the nightly report
SELECT pg_try_advisory_xact_lock(4201) AS got_lock;
```

## Sources

- PostgreSQL 18 manual (checked 2026-10-27): [transaction isolation](https://www.postgresql.org/docs/18/transaction-iso.html), [SET TRANSACTION](https://www.postgresql.org/docs/18/sql-set-transaction.html), [explicit locking](https://www.postgresql.org/docs/18/explicit-locking.html), [SELECT locking clause](https://www.postgresql.org/docs/18/sql-select.html#SQL-FOR-UPDATE-SHARE), [advisory lock functions](https://www.postgresql.org/docs/18/functions-admin.html#FUNCTIONS-ADVISORY-LOCKS), [error codes](https://www.postgresql.org/docs/18/errcodes-appendix.html)
