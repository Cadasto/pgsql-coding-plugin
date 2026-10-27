# Testing queries against PostgreSQL 18

Read when: a test exercises SQL, a repository or a migration, sets up a database for tests, asserts on query results, reproduces a race or a retry, or writes pgTAP tests for functions, constraints or schema.

Deterministic backstop: the test run itself. Go test style belongs to `go-coding:go-testing`, PHPUnit style to php-coding.

## Rules

- **Run tests against the same PostgreSQL major as production.** NULL handling, `ON CONFLICT`, locking and error codes are engine behaviour, so a mock or another engine proves nothing about them. The official `postgres:18` image is current ([Docker Hub](https://hub.docker.com/_/postgres)).
- **In Go, start PostgreSQL with the testcontainers-go postgres module.** Call `postgres.Run` with `WithDatabase`, `WithUsername` and `WithPassword`. Set a wait strategy, because the module supplies none. `postgres.BasicWaitStrategies()` waits for the second "ready to accept connections" log line, since the server restarts once after first start, and then for the port ([testcontainers-go postgres](https://golang.testcontainers.org/modules/postgres/), [wait_strategies.go](https://github.com/testcontainers/testcontainers-go/blob/main/modules/postgres/wait_strategies.go)).
- **Reset state between tests with `Snapshot` and `Restore`, or with a template database.** Snapshots need the `postgres` SQL driver, or `WithSQLDriver("pgx")` with `github.com/jackc/pgx/v5/stdlib` imported. Never name the test database `postgres` ([testcontainers-go postgres](https://golang.testcontainers.org/modules/postgres/)). Without the module, migrate one database, then `CREATE DATABASE test_n TEMPLATE app_template` per test. No other session may be connected to the template while it is copied ([template databases](https://www.postgresql.org/docs/18/manage-ag-templatedbs.html)).
- **Roll back a per-test transaction only when the code under test runs inside that transaction.** A `BEGIN` issued inside it only warns, so the code's own `COMMIT` ends the test transaction ([BEGIN](https://www.postgresql.org/docs/18/sql-begin.html)). Code on another pooled connection sees none of the test's uncommitted rows ([Read Committed](https://www.postgresql.org/docs/18/transaction-iso.html#XACT-READ-COMMITTED)).
- **Make every asserted result order explicit.** Without a unique `ORDER BY`, row order is unspecified and a test passes or fails by chance ([SELECT](https://www.postgresql.org/docs/18/sql-select.html#SQL-LIMIT)).
- **Reproduce a race with two connections, not one.** Open the second transaction while the first holds its lock, then assert the documented outcome: a wait, SQLSTATE `40001`, or `23505` from a concurrent `MERGE` (see `transactions.md` and `writes.md`).
- **Test a constraint with the row it must reject, and assert the SQLSTATE.** The test then fails when the constraint is dropped. Assert the code, not the message text, which changes across releases and locales ([error codes](https://www.postgresql.org/docs/18/errcodes-appendix.html)).
- **Test database objects in SQL with pgTAP.** Wrap each file in `BEGIN; SELECT plan(n); ... SELECT * FROM finish(); ROLLBACK;` and run the files with `pg_prove`. `throws_ok()` asserts an error, `lives_ok()` its absence, and `results_eq()` compares two queries row by row, in order ([pgTAP](https://pgtap.org/documentation.html)).

```go
ctr, err := postgres.Run(ctx, "postgres:18",
	postgres.WithDatabase("app_test"),
	postgres.WithUsername("app"),
	postgres.WithPassword("app"),
	postgres.BasicWaitStrategies(),
	postgres.WithSQLDriver("pgx"),
)
if err != nil {
	t.Fatal(err)
}
dsn, err := ctr.ConnectionString(ctx, "sslmode=disable")
```

```sql
BEGIN;
SELECT plan(2);
SELECT throws_ok(
  $$INSERT INTO orders (customer_id, placed_at) VALUES (-1, now())$$,
  '23503'
);
SELECT results_eq(
  $$SELECT id FROM inactive_customers('2026-10-01') ORDER BY id$$,
  $$VALUES (2::bigint), (5::bigint)$$
);
SELECT * FROM finish();
ROLLBACK;
```

## Sources

- testcontainers-go postgres module: <https://golang.testcontainers.org/modules/postgres/>, <https://github.com/testcontainers/testcontainers-go/blob/main/modules/postgres/wait_strategies.go> (checked 2026-10-27)
- pgTAP 1.3.4 documentation: <https://pgtap.org/documentation.html> (checked 2026-10-27)
- PostgreSQL 18 manual (checked 2026-10-27): [template databases](https://www.postgresql.org/docs/18/manage-ag-templatedbs.html), [SELECT](https://www.postgresql.org/docs/18/sql-select.html), [BEGIN](https://www.postgresql.org/docs/18/sql-begin.html), [transaction isolation](https://www.postgresql.org/docs/18/transaction-iso.html), [error codes](https://www.postgresql.org/docs/18/errcodes-appendix.html)
- Docker official image `postgres`, tag `18`: <https://hub.docker.com/_/postgres> (checked 2026-10-27)
