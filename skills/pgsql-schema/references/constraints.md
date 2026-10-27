# Constraints

Read when: a table gains NOT NULL, CHECK, UNIQUE, PRIMARY KEY, a foreign key and its ON DELETE or ON UPDATE action, DEFERRABLE, EXCLUDE, a temporal key (`WITHOUT OVERLAPS`, `PERIOD`), NOT ENFORCED, or a constraint name.

Backstop: none for design. Squawk checks how a constraint is added to a live table (`constraint-missing-not-valid`), which is `pgsql-migrations`.

## Contents

- NOT NULL and CHECK
- UNIQUE and PRIMARY KEY
- Foreign keys
- DEFERRABLE
- EXCLUDE and temporal keys
- NOT ENFORCED
- Names
- Newer in PostgreSQL 19 (hints)

## Rules

### NOT NULL and CHECK

- **NOT NULL by default.** "In most database designs the majority of columns should be marked not null", and a NOT NULL constraint is cheaper than `CHECK (col IS NOT NULL)` ([constraints](https://www.postgresql.org/docs/18/ddl-constraints.html)). PostgreSQL 18 stores NOT NULL in `pg_constraint`, so it can be named ([release notes](https://www.postgresql.org/docs/18/release-18.html)).
- **A CHECK sees only the row being written.** It must not read other rows or tables, and its functions must be immutable. A CHECK that breaks this "may appear to work in simple tests" yet lets the data drift and can make a dump fail to restore ([constraints](https://www.postgresql.org/docs/18/ddl-constraints.html)).
- **Changing a function a CHECK calls means dropping and re-adding the CHECK.** PostgreSQL does not recheck existing rows when the function changes ([constraints](https://www.postgresql.org/docs/18/ddl-constraints.html)).

### UNIQUE and PRIMARY KEY

- **Nulls are distinct in UNIQUE by default.** Two rows with a null in a constrained column do not conflict. Write `UNIQUE NULLS NOT DISTINCT` when one null must be the only one ([constraints](https://www.postgresql.org/docs/18/ddl-constraints.html)).

```sql
CREATE TABLE product (
    product_id bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    sku        text,
    CONSTRAINT product_sku_key UNIQUE NULLS NOT DISTINCT (sku)
);
```

- **Partitioned tables put the partition key in every PRIMARY KEY and UNIQUE.** See `partitioning.md`.
- **Unique and foreign key checks bypass row-level security.** They can reveal that a hidden row exists; see `security.md`.

### Foreign keys

- **State the ON DELETE action.** The default is `NO ACTION`, which usually raises an error. `RESTRICT` blocks the delete and cannot be deferred. `CASCADE` deletes the referencing rows. `SET NULL` and `SET DEFAULT` can name a column subset, which matters when a referencing column is also part of the key ([constraints](https://www.postgresql.org/docs/18/ddl-constraints.html)).

```sql
FOREIGN KEY (tenant_id, author_id) REFERENCES app_user ON DELETE SET NULL (author_id)
```

- **The referencing columns need an index PostgreSQL does not create** ([constraints](https://www.postgresql.org/docs/18/ddl-constraints.html)); `pgsql-indexing` owns it.
- **Keys and their references share a collation story.** PostgreSQL 18 requires primary and foreign key columns to use deterministic collations or the same nondeterministic one; a restore fails otherwise ([release notes](https://www.postgresql.org/docs/18/release-18.html)).

### DEFERRABLE

- **Only UNIQUE, PRIMARY KEY, EXCLUDE and foreign keys can be deferred.** NOT NULL and CHECK are always immediate ([CREATE TABLE](https://www.postgresql.org/docs/18/sql-createtable.html)).
- **A deferrable constraint cannot be the arbiter of `INSERT ... ON CONFLICT`.** Keep the unique constraint an upsert targets NOT DEFERRABLE ([CREATE TABLE](https://www.postgresql.org/docs/18/sql-createtable.html)).

### EXCLUDE and temporal keys

- **"No two rows overlap" is an exclusion constraint.** UNIQUE "is usually unsuitable for range types"; `EXCLUDE USING gist (during WITH &&)` is the form, and `btree_gist` lets scalar columns join it with `=` ([range types](https://www.postgresql.org/docs/18/rangetypes.html)). The constraint creates its own index ([constraints](https://www.postgresql.org/docs/18/ddl-constraints.html)).
- **A temporal key is `WITHOUT OVERLAPS` on its last column.** `UNIQUE (id, valid_at WITHOUT OVERLAPS)` behaves like `EXCLUDE USING GIST (id WITH =, valid_at WITH &&)`. The column must be a range or multirange, empty ranges are rejected, and scalar key columns need `btree_gist` ([CREATE TABLE](https://www.postgresql.org/docs/18/sql-createtable.html)).
- **A temporal foreign key marks its last column `PERIOD`.** The referenced rows must cover the whole period, the referenced table needs a `WITHOUT OVERLAPS` key, and the actions RESTRICT, CASCADE, SET NULL and SET DEFAULT are not supported ([CREATE TABLE](https://www.postgresql.org/docs/18/sql-createtable.html)).

```sql
CREATE EXTENSION IF NOT EXISTS btree_gist;

CREATE TABLE room_rate (
    room_id  bigint NOT NULL,
    valid_at daterange NOT NULL,
    rate     numeric(10, 2) NOT NULL,
    CONSTRAINT room_rate_pkey PRIMARY KEY (room_id, valid_at WITHOUT OVERLAPS)
);

CREATE TABLE room_booking (
    booking_id bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    room_id    bigint NOT NULL,
    stay       daterange NOT NULL,
    CONSTRAINT room_booking_rate_fkey
        FOREIGN KEY (room_id, PERIOD stay) REFERENCES room_rate (room_id, PERIOD valid_at)
);
```

### NOT ENFORCED

- **Only foreign keys and CHECK constraints can be NOT ENFORCED** in PostgreSQL 18. The database then never checks the rule and the application must keep it; it is meant as documentation where checking costs too much ([CREATE TABLE](https://www.postgresql.org/docs/18/sql-createtable.html), [release notes](https://www.postgresql.org/docs/18/release-18.html)).
- **Prefer an enforced constraint.** With NOT ENFORCED, "it is then up to the application code to ensure that the constraints are satisfied" ([CREATE TABLE](https://www.postgresql.org/docs/18/sql-createtable.html)), so the data can contradict it; state in the migration why the check is too expensive.

### Names

- **Name every constraint a migration will later alter or drop**, so the migration does not depend on a generated name. Keep names under 63 bytes, where PostgreSQL truncates identifiers ([lexical structure](https://www.postgresql.org/docs/18/sql-syntax-lexical.html)).

## Newer in PostgreSQL 19 (hints)

Not rules until PostgreSQL 19 is released ([PostgreSQL 19 release notes](https://www.postgresql.org/docs/19/release-19.html)):

- `ALTER TABLE ... ALTER CONSTRAINT ... [NOT] ENFORCED` works on CHECK constraints, not only foreign keys.
- `CREATE SCHEMA` accepts forward references in `FOREIGN KEY` clauses.
- `error_on_null()` returns its argument or raises an error on null input.

## Sources

- Constraints: <https://www.postgresql.org/docs/18/ddl-constraints.html> (checked 2026-10-27)
- CREATE TABLE (ENFORCED, WITHOUT OVERLAPS, PERIOD, DEFERRABLE, NULLS NOT DISTINCT): <https://www.postgresql.org/docs/18/sql-createtable.html> (checked 2026-10-27)
- Range types, constraints on ranges: <https://www.postgresql.org/docs/18/rangetypes.html> (checked 2026-10-27)
- Lexical structure, identifier length: <https://www.postgresql.org/docs/18/sql-syntax-lexical.html> (checked 2026-10-27)
- PostgreSQL 18 release notes: <https://www.postgresql.org/docs/18/release-18.html> (checked 2026-10-27)
- PostgreSQL 19 release notes, as of 2026-10-09: <https://www.postgresql.org/docs/19/release-19.html> (checked 2026-10-27)
