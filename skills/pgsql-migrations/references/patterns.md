# Recipes for common schema changes

Read when: a migration adds a column, makes a column NOT NULL, adds a CHECK, a foreign key, a unique constraint or a primary key, creates, drops or rebuilds an index, changes a column type, renames or drops a column or table, adds an enum value, backfills data, detaches a partition, or rewrites a whole table.

Backstop: `squawk` flags the unsafe form of each recipe; the rule id is named per recipe. Each "migration" below is its own file and starts with the `SET lock_timeout` and `SET statement_timeout` lines from `lock-levels.md`, except a file of concurrent index statements, which sets both to 0 (same file explains why).

## Contents

- Add a column
- Make an existing column NOT NULL
- Add a CHECK or a foreign key
- Add a unique constraint or primary key
- Create, drop or rebuild an index
- Change a column type
- Rename or drop a column or table
- Add an enum value
- Backfill in batches
- Detach a partition, rewrite a table

## Rules

### Add a column

- **Nullable, or with a non-volatile default: one quick step.** The default is stored in the catalog and no rewrite happens ([ALTER TABLE notes](https://www.postgresql.org/docs/18/sql-altertable.html#SQL-ALTERTABLE-NOTES)). A virtual generated column, the PG 18 default kind, never rewrites either.

```sql
ALTER TABLE orders ADD COLUMN is_gift boolean NOT NULL DEFAULT false;
```

- **A volatile default (such as `clock_timestamp()`), a stored generated column, an identity column or a domain with constraints rewrites the table and its indexes** ([ALTER TABLE notes](https://www.postgresql.org/docs/18/sql-altertable.html#SQL-ALTERTABLE-NOTES)). Add the column nullable, `SET DEFAULT` for new rows, backfill, then make it NOT NULL as below. squawk: `adding-field-with-default`.
- **A `NOT NULL` column without a default fails on a populated table** and breaks older code that inserts without it. squawk: `adding-required-field`.

### Make an existing column NOT NULL

```sql
-- first: deploy code that writes tenant_id on every insert and update,
-- then backfill the NULL rows in batches (below)
-- migration 1: quick ACCESS EXCLUSIVE, no scan; inserts and updates are checked from now on
ALTER TABLE orders ADD CONSTRAINT orders_tenant_id_not_null NOT NULL tenant_id NOT VALID;
-- migration 2: scans the table under SHARE UPDATE EXCLUSIVE
ALTER TABLE orders VALIDATE CONSTRAINT orders_tenant_id_not_null;
```

- **Add the constraint only after the backfill.** A `NOT VALID` constraint is still applied to subsequent inserts and updates ([ALTER TABLE](https://www.postgresql.org/docs/18/sql-altertable.html#SQL-ALTERTABLE-DESC-ADD-TABLE-CONSTRAINT)). Added earlier, it rejects every update of a row still NULL, even one that leaves the column alone, and every insert that omits the column.
- **PG 18 allows `NOT VALID` on not-null constraints,** and `VALIDATE CONSTRAINT` validates them ([release notes 18](https://www.postgresql.org/docs/18/release-18.html), [ALTER TABLE](https://www.postgresql.org/docs/18/sql-altertable.html#SQL-ALTERTABLE-DESC-VALIDATE-CONSTRAINT)).
- **The older route, in the same order:** code writes the column, backfill, then `CHECK (tenant_id IS NOT NULL) NOT VALID`, `VALIDATE CONSTRAINT`, then `SET NOT NULL`, which skips its scan because a valid `CHECK` proves no NULL exists; then drop the `CHECK` ([SET NOT NULL](https://www.postgresql.org/docs/18/sql-altertable.html#SQL-ALTERTABLE-DESC-SET-DROP-NOT-NULL)).
- **A bare `SET NOT NULL` scans the whole table under `ACCESS EXCLUSIVE`.** squawk: `adding-not-nullable-field`.

### Add a CHECK or a foreign key

```sql
-- migration 1: SHARE ROW EXCLUSIVE on orders and tenants, briefly
ALTER TABLE orders ADD CONSTRAINT orders_tenant_id_fkey
    FOREIGN KEY (tenant_id) REFERENCES tenants (id) NOT VALID;
-- migration 2: SHARE UPDATE EXCLUSIVE on orders, ROW SHARE on tenants
ALTER TABLE orders VALIDATE CONSTRAINT orders_tenant_id_fkey;
```

- **Both kinds go `NOT VALID` first and validate later** ([ALTER TABLE notes](https://www.postgresql.org/docs/18/sql-altertable.html#SQL-ALTERTABLE-NOTES)). squawk: `constraint-missing-not-valid`, `adding-foreign-key-constraint`. A row that already breaks a `NOT VALID` `CHECK` rejects any update that leaves it breaking; fix such rows before adding it to a live table.
- **Build the index on the referencing column concurrently, before the foreign key.** Which index is `pgsql-indexing`.

### Add a unique constraint or primary key

```sql
-- migration 1, outside a transaction block
CREATE UNIQUE INDEX CONCURRENTLY orders_external_ref_key ON orders (external_ref);
-- migration 2: quick ACCESS EXCLUSIVE
ALTER TABLE orders ADD CONSTRAINT orders_external_ref_key UNIQUE USING INDEX orders_external_ref_key;
```

- **The index must be a plain b-tree:** no expression columns, not partial, default sort order, and not on a partitioned table ([USING INDEX](https://www.postgresql.org/docs/18/sql-altertable.html#SQL-ALTERTABLE-DESC-ADD-TABLE-CONSTRAINT-USING-INDEX)). The index is renamed to the constraint name.
- **For a `PRIMARY KEY`, make the columns NOT NULL first.** Otherwise `USING INDEX` runs `SET NOT NULL` with a full scan under the strong lock (same page). squawk: `disallowed-unique-constraint`, `adding-serial-primary-key-field`.
- **Uniqueness is enforced against other sessions from the build's second scan,** and a failed build's `INVALID` unique index keeps enforcing it; drop it before retrying ([CREATE INDEX](https://www.postgresql.org/docs/18/sql-createindex.html#SQL-CREATEINDEX-CONCURRENTLY)).

### Create, drop or rebuild an index

- **Create and drop with `CONCURRENTLY`, in a file that runs outside a transaction and sets `lock_timeout` and `statement_timeout` to 0** (`migration-tools.md`, `lock-levels.md`); a short `lock_timeout` aborts the build on a busy system. squawk: `require-concurrent-index-creation`, `require-concurrent-index-deletion`.
- **After a failed build, drop the `INVALID` index before rerunning.** `IF NOT EXISTS` checks only the name, so it keeps the invalid leftover ([CREATE INDEX](https://www.postgresql.org/docs/18/sql-createindex.html)). `pg_index.indisvalid` is false for a possibly incomplete index ([`pg_index`](https://www.postgresql.org/docs/18/catalog-pg-index.html)):

```sql
SELECT indexrelid::regclass FROM pg_index WHERE NOT indisvalid;
DROP INDEX CONCURRENTLY IF EXISTS orders_created_at_idx;
```

- **`DROP INDEX CONCURRENTLY` takes one index and no `CASCADE`,** so it cannot drop an index behind a `UNIQUE` or `PRIMARY KEY` constraint, nor one on a partitioned table ([DROP INDEX](https://www.postgresql.org/docs/18/sql-dropindex.html)).
- **`REINDEX ... CONCURRENTLY` that fails leaves a `_ccnew` or `_ccold` index.** Drop `_ccnew` and retry; drop `_ccold` and stop, the rebuild succeeded ([REINDEX](https://www.postgresql.org/docs/18/sql-reindex.html)). squawk: `require-concurrent-reindex`.
- **A partitioned table has no concurrent build.** Create the parent index `ON ONLY` the parent, which starts invalid and builds nothing; build each partition's index concurrently and attach it. The parent index turns valid once every partition's index is attached ([5.12.2.2](https://www.postgresql.org/docs/18/ddl-partitioning.html#DDL-PARTITIONING-DECLARATIVE-MAINTENANCE)):

```sql
CREATE INDEX events_created_at_idx ON ONLY events (created_at);
-- per partition, outside a transaction block
CREATE INDEX CONCURRENTLY events_2026_10_created_at_idx ON events_2026_10 (created_at);
ALTER INDEX events_created_at_idx ATTACH PARTITION events_2026_10_created_at_idx;
```

### Change a column type

- **A binary-coercible change skips the rewrite,** such as `varchar(n)` to `text` or to a longer `varchar`; indexes may still be rebuilt ([ALTER TABLE notes](https://www.postgresql.org/docs/18/sql-altertable.html#SQL-ALTERTABLE-NOTES)).
- **Any other change, such as `integer` to `bigint`, rewrites the table under `ACCESS EXCLUSIVE`.** Add the new column, keep both written, backfill, switch reads, then drop the old column ([squawk `changing-column-type`](https://squawkhq.com/docs/changing-column-type)).

### Rename or drop a column or table

- **A rename breaks the application version still running.** Keep the database name and rename in code, or for a table: create a view under the new name, deploy, then drop the view and rename in one quick transaction ([squawk `renaming-table`](https://squawkhq.com/docs/renaming-table)). squawk: `renaming-column`, `renaming-table`.
- **Drop only after the code that reads or writes it is gone.** `DROP COLUMN` is quick and frees space only as rows are rewritten ([ALTER TABLE notes](https://www.postgresql.org/docs/18/sql-altertable.html#SQL-ALTERTABLE-NOTES)). squawk: `ban-drop-column`, `ban-drop-table`.

### Add an enum value

```sql
ALTER TYPE order_status ADD VALUE IF NOT EXISTS 'refunded' AFTER 'paid';
```

- **Its own migration, deployed before code writes the value.** Inside a transaction block the new value is unusable until commit; enums have `ADD VALUE` and `RENAME VALUE`, no `DROP VALUE` ([ALTER TYPE](https://www.postgresql.org/docs/18/sql-altertype.html)). squawk: `require-enum-value-ordering`; opt-in `ban-add-enum-value`.

### Backfill in batches

```sql
-- one transaction per batch, run by a script or job, not inside the schema migration
UPDATE orders AS o
SET tenant_id = c.tenant_id
FROM customers AS c
WHERE c.id = o.customer_id
  AND o.id > $1 AND o.id <= $2
  AND o.tenant_id IS NULL;
```

- **Advance `$1` and `$2` over primary-key ranges and commit between batches.** Each batch holds its row locks only until its own commit ([13.3.2](https://www.postgresql.org/docs/18/explicit-locking.html#LOCKING-ROWS)). One long transaction also stops vacuum from removing dead rows ([client settings](https://www.postgresql.org/docs/18/runtime-config-client.html#GUC-IDLE-IN-TRANSACTION-SESSION-TIMEOUT)). Source for batching: [squawk `adding-field-with-default`](https://squawkhq.com/docs/adding-field-with-default).

### Detach a partition, rewrite a table

```sql
ALTER TABLE events DETACH PARTITION events_2025_01 CONCURRENTLY;
```

- **`DETACH PARTITION ... CONCURRENTLY` uses two transactions and `SHARE UPDATE EXCLUSIVE` on the parent.** It cannot run in a transaction block or with a default partition; finish an interrupted one with `FINALIZE` ([DETACH PARTITION](https://www.postgresql.org/docs/18/sql-altertable.html#SQL-ALTERTABLE-DETACH-PARTITION)). squawk: `require-concurrent-partition-detach`.
- **`VACUUM FULL` and `CLUSTER` take `ACCESS EXCLUSIVE`** ([13.3.1](https://www.postgresql.org/docs/18/explicit-locking.html#LOCKING-TABLES)); keep them out of migrations on live tables. PostgreSQL 19's replacement is under the hints in `lock-levels.md`.

## Sources

- PostgreSQL 18, ALTER TABLE (notes, SET NOT NULL, VALIDATE CONSTRAINT, USING INDEX, DETACH PARTITION): <https://www.postgresql.org/docs/18/sql-altertable.html> (checked 2026-10-27)
- PostgreSQL 18, CREATE INDEX: <https://www.postgresql.org/docs/18/sql-createindex.html> (checked 2026-10-27)
- PostgreSQL 18, DROP INDEX and REINDEX: <https://www.postgresql.org/docs/18/sql-dropindex.html>, <https://www.postgresql.org/docs/18/sql-reindex.html> (checked 2026-10-27)
- PostgreSQL 18, partition maintenance (indexes on partitioned tables): <https://www.postgresql.org/docs/18/ddl-partitioning.html> (checked 2026-10-27)
- PostgreSQL 18, `pg_index`: <https://www.postgresql.org/docs/18/catalog-pg-index.html> (checked 2026-10-27)
- PostgreSQL 18, ALTER TYPE: <https://www.postgresql.org/docs/18/sql-altertype.html> (checked 2026-10-27)
- PostgreSQL 18, explicit locking: <https://www.postgresql.org/docs/18/explicit-locking.html> (checked 2026-10-27)
- PostgreSQL 18, client connection defaults: <https://www.postgresql.org/docs/18/runtime-config-client.html> (checked 2026-10-27)
- PostgreSQL 18 release notes: <https://www.postgresql.org/docs/18/release-18.html> (checked 2026-10-27)
- squawk rule pages, linked inline: <https://squawkhq.com/docs/rules> (checked 2026-10-27)
