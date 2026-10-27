# Migration tools and transactions

Read when: a migration runs under goose or golang-migrate, a file holds a statement that cannot run in a transaction block (`CREATE INDEX CONCURRENTLY`, `DROP INDEX CONCURRENTLY`, `REINDEX ... CONCURRENTLY`, `DETACH PARTITION ... CONCURRENTLY`), a file must be safe to rerun, or squawk reports `ban-concurrent-index-creation-in-transaction`, `transaction-nesting` or `prefer-robust-stmts`.

Backstop: squawk with `assume_in_transaction = true`, as in the reference `.squawk.toml` from `/pgsql-lint-setup`, flags a concurrent statement in a file the runner wraps in a transaction.

## Rules

### What PostgreSQL does with a file

- **Several statements sent as one query string run as one transaction.** A simple Query message with more than one statement runs in an implicit transaction block, committed or rolled back as a whole ([54.2.2.1](https://www.postgresql.org/docs/18/protocol-flow.html#PROTOCOL-FLOW-MULTI-STATEMENT)). A runner that sends a whole file as one string wraps it in a transaction even without `BEGIN`.
- **The concurrent forms refuse a transaction block:** `CREATE INDEX CONCURRENTLY` ([CREATE INDEX](https://www.postgresql.org/docs/18/sql-createindex.html#SQL-CREATEINDEX-CONCURRENTLY)), `DROP INDEX CONCURRENTLY` ([DROP INDEX](https://www.postgresql.org/docs/18/sql-dropindex.html)), `REINDEX ... CONCURRENTLY` ([REINDEX](https://www.postgresql.org/docs/18/sql-reindex.html#SQL-REINDEX-CONCURRENTLY)) and `DETACH PARTITION ... CONCURRENTLY` ([ALTER TABLE](https://www.postgresql.org/docs/18/sql-altertable.html#SQL-ALTERTABLE-DETACH-PARTITION)).

### goose

- **Each file runs in one transaction by default.** "All statements within a single migration file are run within the same transaction" ([goose annotations](https://pressly.github.io/goose/documentation/annotations/)).
- **`-- +goose NO TRANSACTION` runs the whole file outside a transaction,** its up and down parts both; place it at the top (same page). Keep such a file to the index statements and their `SET` lines. The `DROP` removes the `INVALID` index a failed earlier run left; without it, `IF NOT EXISTS` would keep that index ([CREATE INDEX](https://www.postgresql.org/docs/18/sql-createindex.html)). It drops a valid index of that name too, so give the index a name no other migration uses. Both timeouts are switched off for this file, for the reasons in `lock-levels.md` (a short `lock_timeout` aborts the build and leaves an `INVALID` index). squawk `require-lock-timeout` fires on concurrent statements too (squawk source, see Sources); `SET lock_timeout = 0` satisfies it and clears a value an earlier file left on the connection:

```sql
-- +goose NO TRANSACTION
-- +goose Up
-- squawk-disable-assume-in-transaction
SET lock_timeout = 0;
SET statement_timeout = 0;
DROP INDEX CONCURRENTLY IF EXISTS orders_tenant_id_idx;
CREATE INDEX CONCURRENTLY IF NOT EXISTS orders_tenant_id_idx ON orders (tenant_id);

-- +goose Down
DROP INDEX CONCURRENTLY IF EXISTS orders_tenant_id_idx;
```

- **Wrap a function body that contains semicolons in `-- +goose StatementBegin` and `-- +goose StatementEnd`,** so goose sends it as one statement (same page).

### golang-migrate

- **A file is sent as one `Exec`.** "In PostgreSQL running multiple SQL statements in one `Exec` executes them inside a transaction" ([golang-migrate postgres](https://github.com/golang-migrate/migrate/blob/master/database/postgres/README.md)).
- **Enable `x-multi-statement=true` in the database URL for a file with a concurrent statement** (same page). The file can then hold the `SET` lines and the drop-then-build pair from the goose example, with `-- squawk-disable-assume-in-transaction`.
- **Without it, the concurrent statement needs a file of its own** (same page). That file cannot switch the timeouts off, so it runs with any `lock_timeout` set on the migration role or in the connection options, which aborts the build on a busy system; prefer `x-multi-statement`. It cannot drop a failed build's leftover either: before rerunning it, find the `INVALID` index and drop it by hand (`patterns.md`).
- **`x-statement-timeout` in the URL sets a statement timeout for the migration statements** (same page).

### Rerunnable files

- **A file outside a transaction can fail halfway and keep its earlier statements.** Write it so a rerun succeeds: `IF NOT EXISTS`, `IF EXISTS` ([squawk `prefer-robust-stmts`](https://squawkhq.com/docs/prefer-robust-stmts)).
- **`IF NOT EXISTS` does not repair a failed concurrent build.** Drop the leftover first, in the same file as above or by hand (`patterns.md`). squawk `prefer-robust-stmts` still asks for `IF NOT EXISTS` on every concurrent build.
- **No `BEGIN` or `COMMIT` in a file the runner already wraps** ([squawk `transaction-nesting`](https://squawkhq.com/docs/transaction-nesting)).

### squawk and the runner

- **`assume_in_transaction = true` matches goose's default and golang-migrate's single `Exec`.** squawk then flags a concurrent statement in a multi-statement file (`ban-concurrent-index-creation-in-transaction`) and `NOT VALID` with `VALIDATE CONSTRAINT` in one file (`constraint-missing-not-valid`) ([squawk CLI](https://squawkhq.com/docs/cli)).
- **A file that runs outside a transaction carries `-- squawk-disable-assume-in-transaction`,** which turns the assumption off for that file only (same page).
- **Set `assume_in_transaction = false` when the runner sends each statement on its own,** with no transaction around the file: the setting means "a transaction will wrap each SQL file when run by a migration tool" (same page).

## Sources

- PostgreSQL 18, frontend/backend protocol, multiple statements in a simple query: <https://www.postgresql.org/docs/18/protocol-flow.html> (checked 2026-10-27)
- PostgreSQL 18, CREATE INDEX, DROP INDEX, REINDEX, ALTER TABLE: <https://www.postgresql.org/docs/18/sql-createindex.html>, <https://www.postgresql.org/docs/18/sql-dropindex.html>, <https://www.postgresql.org/docs/18/sql-reindex.html>, <https://www.postgresql.org/docs/18/sql-altertable.html> (checked 2026-10-27)
- goose annotations: <https://pressly.github.io/goose/documentation/annotations/> (checked 2026-10-27; goose v3.29.0 current)
- golang-migrate PostgreSQL driver: <https://github.com/golang-migrate/migrate/blob/master/database/postgres/README.md> (checked 2026-10-27)
- squawk CLI and configuration, applying migrations safely, rule pages: <https://squawkhq.com/docs/cli>, <https://squawkhq.com/docs/safe_migrations>, <https://squawkhq.com/docs/rules> (checked 2026-10-27)
- squawk source, `require-lock-timeout` on concurrent statements: <https://github.com/sbdchd/squawk/tree/v2.70.0/crates> (checked 2026-10-27; v2.70.0)
