# Writes: upsert, MERGE, RETURNING and bulk statements

Read when: a statement uses `INSERT ... ON CONFLICT`, `EXCLUDED`, `MERGE`, `merge_action()`, `RETURNING`, `old.` or `new.`, inserts, updates or deletes many rows, uses `COPY`, or an application loops over rows sending one statement each.

Deterministic backstop: none. A wrong conflict target fails loudly. Every other mistake here runs clean and loses or duplicates data under concurrency, so cover it with a test that runs two sessions (see `testing.md`).

## Upsert with INSERT ... ON CONFLICT

- **Name the conflict target.** `DO UPDATE` requires one. PostgreSQL infers the arbiter from unique indexes over exactly those columns. For a partial unique index, repeat its predicate in `ON CONFLICT (...) WHERE ...`, or inference fails ([INSERT](https://www.postgresql.org/docs/18/sql-insert.html#SQL-ON-CONFLICT)).
- **Read the proposed row from `EXCLUDED`.** The existing row is the table name or alias. `EXCLUDED` already reflects `BEFORE INSERT` triggers ([INSERT](https://www.postgresql.org/docs/18/sql-insert.html#SQL-ON-CONFLICT)).
- **Deduplicate the input before the upsert.** A statement that would update the same existing row twice raises a cardinality violation, SQLSTATE `21000` ([INSERT](https://www.postgresql.org/docs/18/sql-insert.html#SQL-ON-CONFLICT), [error codes](https://www.postgresql.org/docs/18/errcodes-appendix.html)). Use `DISTINCT ON (key)` with an `ORDER BY` in the source.
- **A row skipped by `DO NOTHING` or by a false `DO UPDATE ... WHERE` is not returned.** `RETURNING` sees only rows inserted or updated ([INSERT](https://www.postgresql.org/docs/18/sql-insert.html)). Fetch the existing row with a second statement when the caller needs it.
- **Tell inserted from updated rows with `old`.** In an `INSERT ... ON CONFLICT DO UPDATE`, `old` values are null for inserted rows and hold the previous row for updated ones ([RETURNING](https://www.postgresql.org/docs/18/dml-returning.html), [INSERT](https://www.postgresql.org/docs/18/sql-insert.html)). Test a `NOT NULL` column.

```sql
INSERT INTO prices (sku, amount, updated_at)
SELECT DISTINCT ON (sku) sku, amount, now()
FROM unnest($1::text[], $2::numeric[]) AS t(sku, amount)
ORDER BY sku
ON CONFLICT (sku) DO UPDATE
  SET amount = EXCLUDED.amount, updated_at = EXCLUDED.updated_at
  WHERE prices.amount IS DISTINCT FROM EXCLUDED.amount
RETURNING sku, (old.sku IS NULL) AS inserted, old.amount AS before, new.amount AS after;
```

## RETURNING old and new

- **`RETURNING` can name `old` and `new` in `INSERT`, `UPDATE`, `DELETE` and `MERGE`.** `old` is normally null in an `INSERT`, and `new` is normally null in a `DELETE` ([RETURNING](https://www.postgresql.org/docs/18/dml-returning.html)). This replaces a separate `SELECT` before an `UPDATE` to capture previous values.
- **Rename them with `RETURNING WITH (OLD AS o, NEW AS n)` when the names clash** with a table alias. Once aliased, `old` and `new` are hidden ([INSERT](https://www.postgresql.org/docs/18/sql-insert.html)).

## MERGE

- **Use `MERGE` to synchronise a target from a source set, not as a concurrent upsert.** Under concurrent inserts of the same key, `MERGE` raises a unique violation, while `ON CONFLICT DO UPDATE` guarantees an insert or an update ([transaction isolation](https://www.postgresql.org/docs/18/transaction-iso.html#XACT-READ-COMMITTED), [MERGE](https://www.postgresql.org/docs/18/sql-merge.html)).
- **Join each target row to at most one source row.** A second match makes a later action fail with a cardinality violation ([MERGE](https://www.postgresql.org/docs/18/sql-merge.html)).
- **Delete what the source no longer holds with `WHEN NOT MATCHED BY SOURCE`.** Its condition may reference only target columns ([MERGE](https://www.postgresql.org/docs/18/sql-merge.html)).
- **Return what happened with `RETURNING merge_action(), ...`.** It reports `INSERT`, `UPDATE` or `DELETE` per row. Qualify columns, because source and target often share names ([merge support functions](https://www.postgresql.org/docs/18/functions-merge-support.html), [RETURNING](https://www.postgresql.org/docs/18/dml-returning.html)).

```sql
MERGE INTO tags t
USING (SELECT * FROM unnest($1::bigint[], $2::text[]) AS s(id, label)) s
  ON t.id = s.id
WHEN MATCHED AND t.label <> s.label THEN UPDATE SET label = s.label
WHEN NOT MATCHED THEN INSERT (id, label) VALUES (s.id, s.label)
WHEN NOT MATCHED BY SOURCE THEN DELETE
RETURNING merge_action(), t.id;
```

## Bulk writes

- **Send arrays, not one statement per row.** Pass one array parameter per column and expand it with `unnest` in `FROM` ([array functions](https://www.postgresql.org/docs/18/functions-array.html), [table functions](https://www.postgresql.org/docs/18/queries-table-expressions.html)). Multi-argument `unnest` pads shorter arrays with nulls, so check that the arrays have equal lengths before sending them.
- **Update or delete many rows by key in one statement.** Use `UPDATE ... FROM unnest(...)` or `DELETE ... WHERE id = ANY($1)` ([UPDATE](https://www.postgresql.org/docs/18/sql-update.html), [row and array comparisons](https://www.postgresql.org/docs/18/functions-comparisons.html)). Send each key once: when a target row joins more than one source row, which one updates it "is not readily predictable" ([UPDATE](https://www.postgresql.org/docs/18/sql-update.html)).
- **Load large sets with `COPY`.** In Go use `CopyFrom`, which "can be faster than an insert with as few as 5 rows" ([pgx docs](https://pkg.go.dev/github.com/jackc/pgx/v5)). In PHP use `Pdo\Pgsql::copyFromArray` ([Pdo\Pgsql](https://www.php.net/manual/en/class.pdo-pgsql.php)). Driver detail is in `go-pgx.md` and `php-pdo.md`.

```sql
UPDATE accounts a
SET balance = a.balance + u.delta
FROM unnest($1::bigint[], $2::numeric[]) AS u(id, delta)
WHERE a.id = u.id
RETURNING a.id, old.balance, new.balance;
```

## Newer in PostgreSQL 19 (hints)

PostgreSQL 19 is a release candidate. These are hints, not rules ([release notes](https://www.postgresql.org/docs/19/release-19.html)).

- `INSERT ... ON CONFLICT DO SELECT ... RETURNING` returns the conflicting rows, optionally locked with `FOR UPDATE` or `FOR SHARE`. It removes the second statement a "get or create" needs today.

## Sources

- PostgreSQL 18 manual (checked 2026-10-27): [INSERT](https://www.postgresql.org/docs/18/sql-insert.html), [MERGE](https://www.postgresql.org/docs/18/sql-merge.html), [merge support functions](https://www.postgresql.org/docs/18/functions-merge-support.html), [UPDATE](https://www.postgresql.org/docs/18/sql-update.html), [row and array comparisons](https://www.postgresql.org/docs/18/functions-comparisons.html), [returning data from modified rows](https://www.postgresql.org/docs/18/dml-returning.html), [transaction isolation](https://www.postgresql.org/docs/18/transaction-iso.html), [array functions](https://www.postgresql.org/docs/18/functions-array.html), [table expressions](https://www.postgresql.org/docs/18/queries-table-expressions.html), [error codes](https://www.postgresql.org/docs/18/errcodes-appendix.html)
- pgx v5 (v5.11.0): <https://pkg.go.dev/github.com/jackc/pgx/v5> (checked 2026-10-27)
- PHP manual, `Pdo\Pgsql`: <https://www.php.net/manual/en/class.pdo-pgsql.php> (checked 2026-10-27)
- PostgreSQL 19 release notes, as of 2026-10-09: <https://www.postgresql.org/docs/19/release-19.html> (checked 2026-10-27)
