---
name: pgsql-schema
description: This skill should be used when a task designs or reviews PostgreSQL tables and the objects around them, for example "design these tables", "which type for money or ids", "should status be an enum", "cascade the delete", "add row-level security per tenant". Covers CREATE TABLE, column types (identity or serial, uuid or uuidv7, text or varchar, timestamptz, numeric for money, enum, domain, array, range or multirange), constraints (NOT NULL, CHECK, UNIQUE NULLS NOT DISTINCT, PRIMARY KEY, FOREIGN KEY with ON DELETE, EXCLUDE, WITHOUT OVERLAPS, PERIOD, NOT ENFORCED, DEFERRABLE), STORED or VIRTUAL generated columns, partitioning, CREATE FUNCTION and PL/pgSQL (volatility, STRICT, SECURITY DEFINER, search_path, EXECUTE format), triggers, GRANT and roles, the public schema, row-level security policies, and views with security_invoker. Not for live-table changes (pgsql-migrations), jsonb columns (pgsql-jsonb), choosing an index (pgsql-indexing), or query text (pgsql-query).
---

# pgsql-schema: tables, types, constraints and database objects

Scope: what a `CREATE TABLE`, `CREATE FUNCTION`, `CREATE TRIGGER`, `CREATE POLICY` or `GRANT` should say on PostgreSQL 18.

Deterministic backstop: `squawk` on migration files flags `serial` (`prefer-identity`), `int` keys (`prefer-bigint-over-int`), `varchar(n)` (`prefer-text-field`), `timestamp` (`prefer-timestamptz`) and `char(n)` (`ban-char-field`). `SELECT * FROM plpgsql_check_function('fn(int)', security_warnings => true)` from the plpgsql_check extension checks each PL/pgSQL function. Name the tool when it would catch the slip; the rules below are the ones that pass both.

## Rules

- **Keys are `bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY`, never `serial`.** The serial types are "not true types" ([numeric types](https://www.postgresql.org/docs/18/datatype-numeric.html)) and the wiki says to use identity columns ([Don't Do This](https://wiki.postgresql.org/wiki/Don%27t_Do_This)). An identity column is NOT NULL but not unique, so it still needs the PRIMARY KEY ([identity columns](https://www.postgresql.org/docs/18/ddl-identity-columns.html)).
- **Use `uuidv7()` when a key is minted outside the database or merged across databases.** It is time-ordered, unlike `gen_random_uuid()`, and anyone holding it can read its creation time with `uuid_extract_timestamp()` ([UUID functions](https://www.postgresql.org/docs/18/functions-uuid.html)). Store it as `uuid`, a 128-bit value, never as `text` ([UUID type](https://www.postgresql.org/docs/18/datatype-uuid.html)).
- **`text` with a CHECK, not `varchar(n)` or `char(n)`.** The three perform the same, and `char(n)` pads with spaces and is usually the slowest ([character types](https://www.postgresql.org/docs/18/datatype-character.html)). Put the real limit in a CHECK ([Don't Do This](https://wiki.postgresql.org/wiki/Don%27t_Do_This)).
- **`timestamptz` for a moment in time.** It is stored as UTC and shown in the session `TimeZone`; `timetz` is not recommended ([date/time types](https://www.postgresql.org/docs/18/datatype-datetime.html)). Plain `timestamp` is a wall-clock reading, not a moment ([Don't Do This](https://wiki.postgresql.org/wiki/Don%27t_Do_This)).
- **`numeric` for money and any exact quantity.** Floating-point types store approximations ([numeric types](https://www.postgresql.org/docs/18/datatype-numeric.html)); `money` depends on `lc_monetary` and stores no currency ([Don't Do This](https://wiki.postgresql.org/wiki/Don%27t_Do_This)). Keep the currency in its own column.
- **NOT NULL unless null means something.** "In most database designs the majority of columns should be marked not null" ([constraints](https://www.postgresql.org/docs/18/ddl-constraints.html)).
- **Lowercase snake_case names, never quoted.** Unquoted names fold to lower case, quoted ones become case-sensitive, and a name past 63 bytes is truncated ([lexical structure](https://www.postgresql.org/docs/18/sql-syntax-lexical.html)). Name constraints and indexes explicitly.
- **Every foreign key states its ON DELETE action.** The default, NO ACTION, usually makes the delete fail ([constraints](https://www.postgresql.org/docs/18/ddl-constraints.html)). The index its referencing columns need is `pgsql-indexing`.
- **Cross-row rules go in UNIQUE, EXCLUDE or FOREIGN KEY, never in a CHECK.** A CHECK is assumed immutable and sees only its own row; one that reads other rows lets bad data in and can break a dump restore ([constraints](https://www.postgresql.org/docs/18/ddl-constraints.html)).
- **Non-overlapping periods use `WITHOUT OVERLAPS` or `EXCLUDE USING gist`.** PostgreSQL 18 adds temporal `PRIMARY KEY` and `UNIQUE ... WITHOUT OVERLAPS` and `FOREIGN KEY ... PERIOD`; scalar columns beside the range need `btree_gist` ([CREATE TABLE](https://www.postgresql.org/docs/18/sql-createtable.html)).
- **Say `STORED` or `VIRTUAL` on every generated column.** VIRTUAL is the PostgreSQL 18 default ([generated columns](https://www.postgresql.org/docs/18/ddl-generated-columns.html)). A virtual column cannot be indexed or carry a primary key or unique constraint ([indexcmds.c](https://github.com/postgres/postgres/blob/REL_18_STABLE/src/backend/commands/indexcmds.c)) and never has statistics ([ALTER TABLE](https://www.postgresql.org/docs/18/sql-altertable.html)), so make it STORED when queries filter on it or it needs an index, as with a value extracted from jsonb.
- **Label function volatility honestly.** VOLATILE is the default, a function that depends on `TimeZone` is STABLE, and a false IMMUTABLE can fold a stale value into a cached plan ([volatility](https://www.postgresql.org/docs/18/xfunc-volatility.html)).
- **Pin `search_path` on SECURITY DEFINER and keep input out of SQL text.** Write `SET search_path = trusted_schema, pg_temp` and revoke EXECUTE from PUBLIC in the same transaction ([CREATE FUNCTION](https://www.postgresql.org/docs/18/sql-createfunction.html)). In PL/pgSQL, pass identifiers through `format('%I', ...)` and values through `EXECUTE ... USING` ([PL/pgSQL statements](https://www.postgresql.org/docs/18/plpgsql-statements.html)).
- **Row-level security does not bind the table owner.** Connect the application as a role that does not own the tables, or add FORCE ROW LEVEL SECURITY ([row security](https://www.postgresql.org/docs/18/ddl-rowsecurity.html)). A view over such a table applies its owner's policies unless created `WITH (security_invoker = true)` ([CREATE VIEW](https://www.postgresql.org/docs/18/sql-createview.html)).
- **Partition only a table that outgrows memory, on the column most queries filter by.** Every PRIMARY KEY and UNIQUE constraint must include the partition key ([partitioning](https://www.postgresql.org/docs/18/ddl-partitioning.html)).

Changing an existing table without blocking writers is `pgsql-migrations`. The shape and indexing of a jsonb column is `pgsql-jsonb`.

## Read the reference

| The task involves | Read |
|---|---|
| a key, a UUID, a string, a time, money, an enum, a domain, an array, a range, a generated column | [types.md](references/types.md) |
| NOT NULL, CHECK, UNIQUE, a foreign key and its ON DELETE, DEFERRABLE, EXCLUDE, WITHOUT OVERLAPS, PERIOD, NOT ENFORCED, constraint names | [constraints.md](references/constraints.md) |
| CREATE FUNCTION or PROCEDURE, PL/pgSQL, volatility, STRICT, PARALLEL, dynamic SQL, a trigger | [functions.md](references/functions.md) |
| roles, GRANT, the public schema, search_path, SECURITY DEFINER, row-level security, a view's privileges | [security.md](references/security.md) |
| PARTITION BY, a default partition, pruning, detaching a partition | [partitioning.md](references/partitioning.md) |

## Sources

- PostgreSQL 18 manual: [data types](https://www.postgresql.org/docs/18/datatype.html), [constraints](https://www.postgresql.org/docs/18/ddl-constraints.html), [CREATE TABLE](https://www.postgresql.org/docs/18/sql-createtable.html), [generated columns](https://www.postgresql.org/docs/18/ddl-generated-columns.html), [partitioning](https://www.postgresql.org/docs/18/ddl-partitioning.html), [CREATE FUNCTION](https://www.postgresql.org/docs/18/sql-createfunction.html), [row security](https://www.postgresql.org/docs/18/ddl-rowsecurity.html) (checked 2026-10-27)
- PostgreSQL 18 release notes: <https://www.postgresql.org/docs/18/release-18.html> (checked 2026-10-27)
- PostgreSQL wiki, Don't Do This: <https://wiki.postgresql.org/wiki/Don%27t_Do_This> (checked 2026-10-27)
- PostgreSQL source, `indexcmds.c` on `REL_18_STABLE`: <https://github.com/postgres/postgres/blob/REL_18_STABLE/src/backend/commands/indexcmds.c> (checked 2026-10-27)
- Squawk rules: <https://squawkhq.com/docs/rules>; plpgsql_check: <https://github.com/okbob/plpgsql_check> (checked 2026-10-27)
