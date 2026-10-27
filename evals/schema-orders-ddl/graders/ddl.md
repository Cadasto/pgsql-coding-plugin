---
type: llm
weight: 2
---

PASS if all of these hold in the SQL:
1. Both ids are `GENERATED ... AS IDENTITY` (or `uuid` defaulting to `uuidv7()`) with a PRIMARY KEY, and neither uses `serial` or `bigserial`.
2. The amount is `numeric` (with or without precision), not `money`, `real`, `double precision` or `float`.
3. The signed-up and placed-at columns are `timestamptz` or `timestamp with time zone`.
4. The status is `text` with a `CHECK (... IN (...))` or a foreign key to a lookup table, not a `CREATE TYPE ... AS ENUM`.
5. The order's customer column is a foreign key with `ON DELETE CASCADE`, and a `CREATE INDEX` covers that column on the order table (or it leads a composite index or primary key).

FAIL if any of these is missing, or if the status is a PostgreSQL enum, or if the foreign key has no index on the referencing column.
