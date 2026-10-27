# Types and generated columns

Read when: a `CREATE TABLE` or `ADD COLUMN` picks a key, a UUID, a string, a time, money, an enum, a domain, an array, a range or multirange, or a generated column.

Backstop: in migration files squawk flags `serial` (`prefer-identity`), `int` keys (`prefer-bigint-over-int`), `varchar(n)` (`prefer-text-field`), `timestamp` (`prefer-timestamptz`) and `char(n)` (`ban-char-field`). Everything else here passes squawk.

## Contents

- Keys
- UUIDs
- Strings
- Time
- Numbers and money
- Enums, CHECK lists and lookup tables
- Domains, arrays, ranges
- Generated columns
- Newer in PostgreSQL 19 (hints)

## Rules

### Keys

- **`GENERATED ALWAYS AS IDENTITY` unless rows arrive with their own ids.** With ALWAYS, an INSERT that supplies a value fails unless it says `OVERRIDING SYSTEM VALUE`; with BY DEFAULT the supplied value wins, like a column default ([identity columns](https://www.postgresql.org/docs/18/ddl-identity-columns.html)). Use BY DEFAULT only for imports that keep source ids.
- **Declare the PRIMARY KEY.** "An identity column, however, does not guarantee uniqueness" ([identity columns](https://www.postgresql.org/docs/18/ddl-identity-columns.html)).
- **`bigint` for keys that grow.** `integer` ends at 2147483647 ([numeric types](https://www.postgresql.org/docs/18/datatype-numeric.html)); widening a key later means migrating it and every column that references it (`pgsql-migrations`).
- **No `serial` in new tables.** The wiki keeps it only for a sequence shared by several tables ([Don't Do This](https://wiki.postgresql.org/wiki/Don%27t_Do_This)).

```sql
CREATE TABLE customer (
    customer_id  bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    display_name text NOT NULL CHECK (char_length(display_name) BETWEEN 1 AND 200),
    created_at   timestamptz NOT NULL DEFAULT now()
);
```

### UUIDs

- **Pick a UUID key only when it earns its 16 bytes.** UUIDs suit ids minted by clients or several databases, since a sequence is unique only within one database ([UUID type](https://www.postgresql.org/docs/18/datatype-uuid.html)). Otherwise a `bigint` identity is 8 bytes ([numeric types](https://www.postgresql.org/docs/18/datatype-numeric.html)).
- **Generate keys with `uuidv7()`.** It is time-ordered, with millisecond precision, where `uuidv4()` and `gen_random_uuid()` are random ([UUID functions](https://www.postgresql.org/docs/18/functions-uuid.html)); the release announcement credits it with "better indexing and read performance" ([PostgreSQL 18 released](https://www.postgresql.org/about/news/postgresql-18-released-3142/)).
- **A v7 UUID discloses when it was made.** `uuid_extract_timestamp()` returns the time from a version 1 or 7 UUID ([UUID functions](https://www.postgresql.org/docs/18/functions-uuid.html)). Use `uuidv4()` for a public token where that time is private.
- **Store the `uuid` type, never `text`.** It is a 128-bit value, accepts upper case, braces and missing hyphens on input, and always prints the standard form ([UUID type](https://www.postgresql.org/docs/18/datatype-uuid.html)).

### Strings

- **`text`, with a CHECK when a limit is real.** `text`, `varchar` and `char(n)` perform the same, `char(n)` costs extra storage and is usually the slowest ([character types](https://www.postgresql.org/docs/18/datatype-character.html)). `varchar(n)` only adds an arbitrary error ([Don't Do This](https://wiki.postgresql.org/wiki/Don%27t_Do_This)).
- **No `char(n)`, even for fixed-width codes.** It pads with spaces and ignores trailing spaces when comparing, while `text` keeps them ([character types](https://www.postgresql.org/docs/18/datatype-character.html)).

```sql
country_code text NOT NULL CHECK (country_code ~ '^[A-Z]{2}$')
```

### Time

- **`timestamptz` for a moment.** Input is converted to UTC, input without a zone uses the session `TimeZone`, and output is converted back to that zone ([date/time types](https://www.postgresql.org/docs/18/datatype-datetime.html)).
- **Plain `timestamp` is a calendar and a clock, not a moment.** Arithmetic across zones and daylight-saving changes goes wrong on it ([Don't Do This](https://wiki.postgresql.org/wiki/Don%27t_Do_This)).
- **No `timetz`.** The manual does not recommend it ([date/time types](https://www.postgresql.org/docs/18/datatype-datetime.html)).
- **Type literals explicitly.** `TIMESTAMP '2004-10-19 10:23:54+02'` is read as `timestamp without time zone`; write `TIMESTAMPTZ '...'` ([date/time types](https://www.postgresql.org/docs/18/datatype-datetime.html)).
- **No precision 0.** `timestamptz(0)` rounds rather than truncates ([Don't Do This](https://wiki.postgresql.org/wiki/Don%27t_Do_This)).

### Numbers and money

- **`numeric` for money and exact quantities.** Floating-point types are inexact; "use the `numeric` type instead" ([numeric types](https://www.postgresql.org/docs/18/datatype-numeric.html)).
- **No `money`.** It stores no currency, depends on `lc_monetary` and cannot hold fractions of a cent ([Don't Do This](https://wiki.postgresql.org/wiki/Don%27t_Do_This)).

```sql
amount   numeric(14, 2) NOT NULL CHECK (amount >= 0),
currency text NOT NULL CHECK (currency ~ '^[A-Z]{3}$')
```

### Enums, CHECK lists and lookup tables

- **An enum suits a closed set that only grows.** Values can be added and renamed, but not removed or reordered without dropping and re-creating the type ([enum types](https://www.postgresql.org/docs/18/datatype-enum.html)).
- **Values that may be retired use `CHECK (status IN (...))` or a lookup table with a foreign key.** A lookup table also fits values that carry attributes. Adding an enum value in a migration is `pgsql-migrations`.

### Domains, arrays, ranges

- **A domain holds a rule several tables share.** Let the domain allow null and put NOT NULL on each column: a domain's NOT NULL can be bypassed by an outer join or an empty subquery ([CREATE DOMAIN](https://www.postgresql.org/docs/18/sql-createdomain.html)). Its CHECK must be immutable and should not raise errors.
- **Arrays are not sets.** "Searching for specific array elements can be a sign of database misdesign"; use a child table instead ([arrays](https://www.postgresql.org/docs/18/arrays.html)). jsonb arrays are `pgsql-jsonb`.
- **A period is a range, not two columns.** Built-in discrete ranges use `[)` bounds, and a GiST index serves `&&`, `@>` and `<@` ([range types](https://www.postgresql.org/docs/18/rangetypes.html)). Non-overlap rules are in `constraints.md`.

### Generated columns

- **Write `STORED` or `VIRTUAL`.** VIRTUAL is the default and is computed on read; STORED is computed on write ([generated columns](https://www.postgresql.org/docs/18/ddl-generated-columns.html)).
- **The expression is immutable and row-local.** No subqueries, no other generated column, no default or identity, and never a partition key column ([generated columns](https://www.postgresql.org/docs/18/ddl-generated-columns.html)).
- **A virtual column uses built-in functions and types only.** No user-defined type or function, directly or through an operator or cast ([generated columns](https://www.postgresql.org/docs/18/ddl-generated-columns.html)).
- **A virtual column cannot be indexed.** PostgreSQL 18 rejects indexes, primary keys and unique constraints on it ([indexcmds.c](https://github.com/postgres/postgres/blob/REL_18_STABLE/src/backend/commands/indexcmds.c)), and it never has statistics ([ALTER TABLE](https://www.postgresql.org/docs/18/sql-altertable.html)).
- **Choose STORED when a query filters or sorts on the value, it needs an index, or it must replicate.** This includes a scalar extracted from a jsonb document. Only stored generated columns replicate logically ([generated columns](https://www.postgresql.org/docs/18/ddl-generated-columns.html)). Adding a VIRTUAL column never rewrites the table ([ALTER TABLE](https://www.postgresql.org/docs/18/sql-altertable.html)). An expression index on the source columns is the other route (`pgsql-indexing`).

```sql
total numeric GENERATED ALWAYS AS (quantity * unit_price) STORED
```

## Newer in PostgreSQL 19 (hints)

Not rules until PostgreSQL 19 is released ([PostgreSQL 19 release notes](https://www.postgresql.org/docs/19/release-19.html)):

- A 64-bit unsigned `oid8` type.
- Extended statistics on virtual generated columns.
- `ALTER TABLE ... SET EXPRESSION` on a virtual column with a CHECK constraint.
- `range_minus_multi()` and `multirange_minus_multi()` return range subtraction results that have gaps.

## Sources

- Identity columns: <https://www.postgresql.org/docs/18/ddl-identity-columns.html> (checked 2026-10-27)
- Numeric, character, date/time, UUID, enum, array and range types: <https://www.postgresql.org/docs/18/datatype-numeric.html>, <https://www.postgresql.org/docs/18/datatype-character.html>, <https://www.postgresql.org/docs/18/datatype-datetime.html>, <https://www.postgresql.org/docs/18/datatype-uuid.html>, <https://www.postgresql.org/docs/18/datatype-enum.html>, <https://www.postgresql.org/docs/18/arrays.html>, <https://www.postgresql.org/docs/18/rangetypes.html> (checked 2026-10-27)
- UUID functions: <https://www.postgresql.org/docs/18/functions-uuid.html> (checked 2026-10-27)
- CREATE DOMAIN: <https://www.postgresql.org/docs/18/sql-createdomain.html> (checked 2026-10-27)
- Generated columns: <https://www.postgresql.org/docs/18/ddl-generated-columns.html>; ALTER TABLE: <https://www.postgresql.org/docs/18/sql-altertable.html> (checked 2026-10-27)
- Virtual column index errors, `indexcmds.c` on `REL_18_STABLE`: <https://github.com/postgres/postgres/blob/REL_18_STABLE/src/backend/commands/indexcmds.c> (checked 2026-10-27)
- PostgreSQL 18 release announcement: <https://www.postgresql.org/about/news/postgresql-18-released-3142/> (checked 2026-10-27)
- PostgreSQL wiki, Don't Do This: <https://wiki.postgresql.org/wiki/Don%27t_Do_This> (checked 2026-10-27)
- PostgreSQL 19 release notes, as of 2026-10-09: <https://www.postgresql.org/docs/19/release-19.html> (checked 2026-10-27)
