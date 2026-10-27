---
name: pgsql-query
description: This skill should be used before writing, reviewing or debugging any PostgreSQL query or statement, including SQL in Go or PHP code, for example "find customers with no orders this month", "paginate this list", "upsert", "bulk insert", "make this job queue safe", "retry on a serialization failure or deadlock", "why does NOT IN return no rows". Covers NULLs and IS DISTINCT FROM, NOT EXISTS, LATERAL, WITH and MATERIALIZED, recursive CTEs, window frames and FILTER, DISTINCT ON, keyset pagination, timestamptz ranges, INSERT ON CONFLICT, MERGE, RETURNING old and new, unnest and COPY, = ANY($1), isolation levels, FOR UPDATE SKIP LOCKED, advisory locks, SQLSTATE handling, identifier quoting, pgx v5 and pgxpool (NamedArgs, CollectRows, SendBatch, CopyFrom, QueryExecMode, PgError), PDO (placeholders, PARAM_BOOL, bytea) and tests on a real PostgreSQL 18. Not for jsonb (pgsql-jsonb), indexes (pgsql-indexing), EXPLAIN (pgsql-performance), table design (pgsql-schema) or DDL rollout (pgsql-migrations).
---

# pgsql-query: statements and the driver boundary

Scope: the SQL text of a query or write on PostgreSQL 18, and how Go (pgx v5) or PHP (PDO pgsql) sends it and reads the result.

Deterministic backstop: none decides query semantics. Prove a statement with a test against the production major, PostgreSQL 18, never a mock or another engine ([testing.md](references/testing.md)). Plan cost belongs to `pgsql-performance`, index choice to `pgsql-indexing`, and migration linting to `pgsql-migrations`.

## Rules

- **Test for NULL with `IS NULL` or `IS [NOT] DISTINCT FROM`, never `= NULL`.** Ordinary comparisons with a null yield null, not true or false ([comparison operators](https://www.postgresql.org/docs/18/functions-comparison.html)).
- **Write an anti-join as `NOT EXISTS`, not `NOT IN (subquery)`.** If the subquery returns a null and no row matches, `NOT IN` yields null, so the query returns no rows ([subquery expressions](https://www.postgresql.org/docs/18/functions-subquery.html), [Don't Do This](https://wiki.postgresql.org/wiki/Don%27t_Do_This)).
- **Give every `LIMIT` an `ORDER BY` that ends in a unique key, and page with a keyset.** Without a unique order the page is "an unpredictable subset", and rows skipped by `OFFSET` "still have to be computed" ([SELECT](https://www.postgresql.org/docs/18/sql-select.html#SQL-LIMIT), [LIMIT and OFFSET](https://www.postgresql.org/docs/18/queries-limit.html)).
- **Filter time with a half-open range on `timestamptz`.** Write `>= start AND < end`; `BETWEEN` includes both ends and double-counts the boundary ([Don't Do This](https://wiki.postgresql.org/wiki/Don%27t_Do_This)).
- **Wrap `sum`, `max` and `array_agg` in `coalesce` when zero rows are possible.** Every aggregate except `count` returns null over no rows ([aggregate functions](https://www.postgresql.org/docs/18/functions-aggregate.html)).
- **Pass a list as one array parameter: `= ANY($1)`.** Never build an `IN (...)` string; `IN ($1)` compares against the whole array ([row and array comparisons](https://www.postgresql.org/docs/18/functions-comparisons.html), [PDO::prepare](https://www.php.net/manual/en/pdo.prepare.php)).
- **Upsert with `INSERT ... ON CONFLICT`, not `MERGE`, when concurrent inserts can collide.** Only `ON CONFLICT DO UPDATE` guarantees an insert or an update; `MERGE` raises a unique violation instead ([transaction isolation](https://www.postgresql.org/docs/18/transaction-iso.html)).
- **Expect no row back from `ON CONFLICT DO NOTHING` for a conflicting key.** `RETURNING` returns only rows inserted or updated ([INSERT](https://www.postgresql.org/docs/18/sql-insert.html)).
- **Write many rows in one statement.** Use `unnest` over array parameters or `COPY` (`CopyFrom` in pgx), not a loop of single-row statements ([array functions](https://www.postgresql.org/docs/18/functions-array.html), [pgx docs](https://pkg.go.dev/github.com/jackc/pgx/v5)).
- **Bind values; take identifiers from an allowlist.** A parameter is one complete value, never a table or column name ([PDO::prepare](https://www.php.net/manual/en/pdo.prepare.php)). In Go, quote an allowlisted name with `pgx.Identifier{...}.Sanitize()` ([pgx docs](https://pkg.go.dev/github.com/jackc/pgx/v5#Identifier.Sanitize)). For PHP, follow the php-coding security reference; for PL/pgSQL `EXECUTE`, see `pgsql-schema`.
- **Retry the whole transaction on SQLSTATE `40001` and `40P01`.** Repeatable Read and Serializable require the retry for `40001`; `40P01` can occur at any level. Test the code, never the message text ([transaction isolation](https://www.postgresql.org/docs/18/transaction-iso.html), [deadlocks](https://www.postgresql.org/docs/18/explicit-locking.html#LOCKING-DEADLOCKS), [error codes](https://www.postgresql.org/docs/18/errcodes-appendix.html)).
- **Claim queue rows with `FOR UPDATE SKIP LOCKED`, and keep transactions short.** `SKIP LOCKED` gives an inconsistent view meant only for queue-like tables. A transaction left open while waiting for input blocks other lockers indefinitely ([SELECT](https://www.postgresql.org/docs/18/sql-select.html), [explicit locking](https://www.postgresql.org/docs/18/explicit-locking.html)).
- **Close every result set and check its error.** In pgx, `CollectRows` closes the rows. With a manual loop, check `rows.Err()` after `Next` returns false ([pgx docs](https://pkg.go.dev/github.com/jackc/pgx/v5)).
## Read the reference

| The task involves | Read |
|---|---|
| NULLs, `EXISTS`, `LEFT JOIN` conditions, `LATERAL`, CTEs, recursion, window functions, `FILTER`, `DISTINCT ON`, pagination, `timestamptz`, `AT TIME ZONE` | [idioms.md](references/idioms.md) |
| `INSERT ... ON CONFLICT`, `MERGE`, `RETURNING old/new`, bulk insert, update or delete from arrays, `COPY` | [writes.md](references/writes.md) |
| isolation levels, retries, deadlocks, `FOR UPDATE`, `SKIP LOCKED`, `NOWAIT`, advisory locks, SQLSTATE codes | [transactions.md](references/transactions.md) |
| Go: `pgx`, `pgxpool`, `pgconn.PgError`, `NamedArgs`, `CollectRows`, a query per row in a loop, `SendBatch`, `CopyFrom`, `QueryExecMode`, generic plans, PgBouncer, type mapping | [go-pgx.md](references/go-pgx.md) |
| PHP: `PDO`, `Pdo\Pgsql`, placeholders, `PARAM_BOOL`, `bytea`, `PDOException` SQLSTATE, `copyFromArray` | [php-pdo.md](references/php-pdo.md) |
| tests: testcontainers-go, template databases, per-test isolation, pgTAP | [testing.md](references/testing.md) |

jsonb operators, SQL/JSON functions and their driver mapping belong to `pgsql-jsonb`. The host language (error wrapping, test style) belongs to go-coding or php-coding.

## Sources

- PostgreSQL 18 manual: [comparison](https://www.postgresql.org/docs/18/functions-comparison.html), [subqueries](https://www.postgresql.org/docs/18/functions-subquery.html), [SELECT](https://www.postgresql.org/docs/18/sql-select.html), [LIMIT](https://www.postgresql.org/docs/18/queries-limit.html), [aggregates](https://www.postgresql.org/docs/18/functions-aggregate.html), [INSERT](https://www.postgresql.org/docs/18/sql-insert.html), [transaction isolation](https://www.postgresql.org/docs/18/transaction-iso.html), [explicit locking](https://www.postgresql.org/docs/18/explicit-locking.html), [error codes](https://www.postgresql.org/docs/18/errcodes-appendix.html), [array functions](https://www.postgresql.org/docs/18/functions-array.html), [row and array comparisons](https://www.postgresql.org/docs/18/functions-comparisons.html) (checked 2026-10-27)
- PostgreSQL wiki, Don't Do This: <https://wiki.postgresql.org/wiki/Don%27t_Do_This> (checked 2026-10-27)
- pgx v5 (v5.11.0): <https://pkg.go.dev/github.com/jackc/pgx/v5> (checked 2026-10-27)
- PHP manual, PDO::prepare: <https://www.php.net/manual/en/pdo.prepare.php> (checked 2026-10-27)
