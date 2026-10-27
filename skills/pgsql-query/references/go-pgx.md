# Go with pgx v5 and pgxpool

Read when: a `.go` file imports `github.com/jackc/pgx/v5`, `pgxpool`, `pgconn`, `pgtype` or `pgerrcode`, calls `Query`, `QueryRow`, `Exec`, `SendBatch`, `CopyFrom` or `BeginTxFunc`, branches on a database error, or runs behind PgBouncer.

Deterministic backstop: `go vet` and `golangci-lint`, owned by go-coding. Error wrapping and `errors.AsType` style belong to `go-coding:go-errors`, tests to `go-coding:go-testing`. jsonb mapping belongs to `pgsql-jsonb`.

## Contents

- Placeholders and arguments
- Reading rows
- Errors and retries
- Transactions and context
- Pool and PgBouncer
- Batches and COPY
- Type mapping

## Placeholders and arguments

- **Reference arguments as `$1`, `$2`.** With `pgx.NamedArgs`, write `@name`. Names are case sensitive and start with a letter or underscore ([pgx](https://pkg.go.dev/github.com/jackc/pgx/v5), [named_args.go](https://github.com/jackc/pgx/blob/v5.11.0/named_args.go)).
- **Prefer `pgx.StrictNamedArgs` over `pgx.NamedArgs`.** It checks that the query uses every argument given, and that every argument it uses is given ([pgx](https://pkg.go.dev/github.com/jackc/pgx/v5#StrictNamedArgs)).
- **Do not run one query per row in a loop.** Fetch or write the set in one statement with `= ANY($1)` or `unnest` (see `writes.md`). When the statements differ, queue them in a `pgx.Batch`, which bundles queries "to avoid unnecessary network round trips" ([batch.go](https://github.com/jackc/pgx/blob/v5.11.0/batch.go)).

## Reading rows

- **Collect with `pgx.CollectRows`.** It "closes the rows automatically on return". Map columns with `pgx.RowToStructByName[T]`, which matches case-insensitively and honours a `db:"name"` tag ([pgx](https://pkg.go.dev/github.com/jackc/pgx/v5#CollectRows)).
- **In a manual loop, close the rows and then check `rows.Err()`.** Rows "must be closed before the connection can be used again", and `Err` must be checked after `Next` returns false ([conn.go](https://github.com/jackc/pgx/blob/v5.11.0/conn.go)).
- **Treat no row as a value, not a failure, where the caller expects it.** `QueryRow(...).Scan` and `CollectOneRow` return an error matching `errors.Is(err, pgx.ErrNoRows)`. `CollectExactlyOneRow` also returns `pgx.ErrTooManyRows` ([pgx](https://pkg.go.dev/github.com/jackc/pgx/v5#CollectOneRow)).

```go
type Customer struct {
	ID   int64  `db:"id"`
	Name string `db:"name"`
}

rows, err := pool.Query(ctx, `SELECT id, name FROM customers WHERE id = ANY($1) ORDER BY name, id`, ids)
if err != nil {
	return nil, fmt.Errorf("customers by id: %w", err)
}
customers, err := pgx.CollectRows(rows, pgx.RowToStructByName[Customer])
```

## Errors and retries

- **Read the SQLSTATE from `*pgconn.PgError`.** `Code` holds it, and `ConstraintName`, `TableName` and `ColumnName` say where it came from. Compare with the `pgerrcode` constants (`UniqueViolation`, `SerializationFailure`, `DeadlockDetected`) ([pgconn](https://pkg.go.dev/github.com/jackc/pgx/v5/pgconn#PgError), [pgerrcode](https://pkg.go.dev/github.com/jackc/pgerrcode)).
- **Keep `Message` and `Detail` inside the service.** The server's text can quote stored values. Pass the code across a log or API boundary (see `go-coding:go-errors`).
- **Retry named codes, not the whole class 40.** `pgerrcode.IsTransactionRollback` matches every class 40 code ([pgerrcode](https://pkg.go.dev/github.com/jackc/pgerrcode)). Retry `40001` and `40P01` by name; see `transactions.md`. `pgconn.SafeToRetry(err)` is true only when the error happened before any data reached the server ([pgconn](https://pkg.go.dev/github.com/jackc/pgx/v5/pgconn#SafeToRetry)).

```go
func inSerializableTx(ctx context.Context, pool *pgxpool.Pool, fn func(pgx.Tx) error) error {
	var err error
	for range 3 {
		err = pgx.BeginTxFunc(ctx, pool, pgx.TxOptions{IsoLevel: pgx.Serializable}, fn)
		pgErr, ok := errors.AsType[*pgconn.PgError](err)
		if !ok || (pgErr.Code != pgerrcode.SerializationFailure && pgErr.Code != pgerrcode.DeadlockDetected) {
			return err
		}
	}
	return err
}
```

## Transactions and context

- **Use `pgx.BeginFunc` or `pgx.BeginTxFunc`.** They commit when the callback returns nil and roll back when it returns an error ([pgx](https://pkg.go.dev/github.com/jackc/pgx/v5#BeginTxFunc)). With a manual `Begin`, `defer tx.Rollback(ctx)` is safe even after `Commit` ([pgx](https://pkg.go.dev/github.com/jackc/pgx/v5#Tx)).
- **Pass the request context to every call.** When it is canceled, the method returns at once and the connection is usually closed, so frequent cancels churn connections. `BuildContextWatcherHandler` on the config changes that ([pgconn doc.go](https://github.com/jackc/pgx/blob/v5.11.0/pgconn/doc.go)).

## Pool and PgBouncer

- **Share one `*pgxpool.Pool` per database.** It is concurrency-safe and returns before any connection exists, so call `pool.Ping(ctx)` at startup to fail fast ([pgxpool](https://pkg.go.dev/github.com/jackc/pgx/v5/pgxpool)).
- **Release every acquired connection.** `Pool.Exec`, `Pool.Query` (once its rows close) and `AcquireFunc` release automatically; a bare `Acquire` needs `Release` ([pgxpool](https://pkg.go.dev/github.com/jackc/pgx/v5/pgxpool#Conn.Release)).
- **Register custom types in `AfterConnect`**, before the connection joins the pool. `PrepareConn` replaces the deprecated `BeforeAcquire` ([pgxpool](https://pkg.go.dev/github.com/jackc/pgx/v5/pgxpool#Config)).
- **Pick `QueryExecMode` for the pooler.** The default caches prepared statements, which PgBouncer 1.21.0 and newer supports. With an older PgBouncer, use `QueryExecModeExec`, preferred over `QueryExecModeSimpleProtocol`. Never use `QueryExecModeDescribeExec` with transaction pooling ([pgx doc.go](https://github.com/jackc/pgx/blob/v5.11.0/doc.go)).
- **Know which modes reuse a plan.** The default mode prepares a statement on first execution and reuses it ([pgx doc.go](https://github.com/jackc/pgx/blob/v5.11.0/doc.go)). The server's generic-plan switch then applies (`pgsql-performance`). `QueryExecModeExec` caches no statement and `QueryExecModeSimpleProtocol` interpolates values on the client, so each execution is planned for its own values ([conn.go](https://github.com/jackc/pgx/blob/v5.11.0/conn.go)).

## Batches and COPY

- **`SendBatch` runs its queries in one implicit transaction,** unless the batch has its own transaction control. Close the `BatchResults` before reusing the connection. Statements may be prepared up front, so a batch that creates a table and then uses it can fail ([conn.go](https://github.com/jackc/pgx/blob/v5.11.0/conn.go), [pgx](https://pkg.go.dev/github.com/jackc/pgx/v5#Batch)).
- **Bulk-load with `CopyFrom`** and `pgx.CopyFromSlice` or `pgx.CopyFromRows`. It uses the binary format, so every column type must be known to the connection; register enum types with `LoadType` and `RegisterType` first ([pgx](https://pkg.go.dev/github.com/jackc/pgx/v5#Conn.CopyFrom)).

## Type mapping

- **NULL needs a pointer or a `pgtype` value.** Scan into `*string`, or into `pgtype.Text` and read `Valid`. When encoding a `pgtype` value, set `Valid: true` or it is sent as NULL ([pgtype](https://pkg.go.dev/github.com/jackc/pgx/v5/pgtype)).
- **`timestamptz` scans into `time.Time` in `time.Local` by default.** The instant is right and the location is the host's. Set `ScanLocation` on `pgtype.TimestamptzCodec` to change it, and compare instants with `Time.Equal` ([timestamptz.go](https://github.com/jackc/pgx/blob/v5.11.0/pgtype/timestamptz.go)). Infinite values appear in `pgtype.Timestamptz.InfinityModifier`.
- **Do not scan `numeric` money into `float64`.** `numeric` exists for exact quantities and floating point is inexact ([numeric types](https://www.postgresql.org/docs/18/datatype-numeric.html)). Use `pgtype.Numeric`, or register `github.com/jackc/pgx-shopspring-decimal` for `decimal.Decimal` ([pgtype](https://pkg.go.dev/github.com/jackc/pgx/v5/pgtype), [pgx-shopspring-decimal](https://pkg.go.dev/github.com/jackc/pgx-shopspring-decimal)).
- **`uuid` scans into `pgtype.UUID`.** Other UUID libraries need a registered integration, such as `github.com/jackc/pgx-gofrs-uuid` ([pgtype](https://pkg.go.dev/github.com/jackc/pgx/v5/pgtype)).
- **Arrays scan straight into a matching Go slice,** including the result of `array_agg` ([pgx doc.go](https://github.com/jackc/pgx/blob/v5.11.0/doc.go)).

```go
cfg.AfterConnect = func(ctx context.Context, conn *pgx.Conn) error {
	pgxdecimal.Register(conn.TypeMap()) // pgxdecimal "github.com/jackc/pgx-shopspring-decimal"
	return nil
}
```

## Sources

- pgx v5.11.0 (2026-09-07), package docs and source (checked 2026-10-27): <https://pkg.go.dev/github.com/jackc/pgx/v5>, <https://pkg.go.dev/github.com/jackc/pgx/v5/pgconn>, <https://pkg.go.dev/github.com/jackc/pgx/v5/pgxpool>, <https://pkg.go.dev/github.com/jackc/pgx/v5/pgtype>, <https://github.com/jackc/pgx/blob/v5.11.0/doc.go>, <https://github.com/jackc/pgx/blob/v5.11.0/conn.go>, <https://github.com/jackc/pgx/blob/v5.11.0/named_args.go>, <https://github.com/jackc/pgx/blob/v5.11.0/pgconn/doc.go>, <https://github.com/jackc/pgx/blob/v5.11.0/pgtype/timestamptz.go>
- pgerrcode: <https://pkg.go.dev/github.com/jackc/pgerrcode> (checked 2026-10-27)
- pgx-shopspring-decimal: <https://pkg.go.dev/github.com/jackc/pgx-shopspring-decimal> (checked 2026-10-27)
- PostgreSQL 18 manual (checked 2026-10-27): [numeric types](https://www.postgresql.org/docs/18/datatype-numeric.html)
- pgx v5.11.0 `batch.go`: <https://github.com/jackc/pgx/blob/v5.11.0/batch.go> (checked 2026-10-27)
