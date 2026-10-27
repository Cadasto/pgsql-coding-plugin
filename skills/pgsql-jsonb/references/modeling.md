# Modelling with jsonb

Read when: choosing `json` or `jsonb`; deciding whether a field lives in a document or in a column; adding a generated column from a document key; validating document shape with a `CHECK`; storing large or frequently updated documents; storing money, identifiers or big integers inside JSON.

Deterministic backstop: none for the design itself. `\d+ table` shows column storage; `pg_column_size(doc)` shows the stored size of one value. General table design (types, keys, constraints, partitioning) belongs to `pgsql-schema`.

## Rules

- **Store `jsonb`, not `json`.** `json` keeps the input text and reparses it on every call; `jsonb` is "significantly faster to process" and supports indexing. "Most applications should prefer to store JSON data as `jsonb`, unless there are quite specialized needs, such as legacy assumptions about ordering of object keys" ([JSON types](https://www.postgresql.org/docs/18/datatype-json.html)). `jsonb` drops white space, key order and duplicate keys (the last one wins).
- **Give documents a predictable shape.** The manual recommends "that JSON documents have a somewhat fixed structure" even where flexibility is the point, because predictable structure is what makes documents queryable ([designing JSON documents](https://www.postgresql.org/docs/18/datatype-json.html#JSON-DOC-DESIGN)).
- **Promote a key to a real column when the database must enforce or join on it.** A foreign key references columns, not expressions inside a document ([foreign keys](https://www.postgresql.org/docs/18/ddl-constraints.html#DDL-CONSTRAINTS-FK)). A key that is joined on, sorted by, range-filtered, or that needs `NOT NULL`, `UNIQUE` or a foreign key belongs in a column. Keep the document for the attributes that vary between rows.
- **Generate the column when the document stays the source of truth.** `GENERATED ALWAYS AS ((doc ->> 'customer_id')::bigint) STORED` keeps the two in step ([generated columns](https://www.postgresql.org/docs/18/ddl-generated-columns.html)); indexing it is covered in `indexing.md`.
- **Keep documents small when they are updated.** "Any update acquires a row-level lock on the whole row"; the manual advises limiting documents "to a manageable size in order to decrease lock contention" and making each one "an atomic datum" ([designing JSON documents](https://www.postgresql.org/docs/18/datatype-json.html#JSON-DOC-DESIGN)).
- **A one-key update rewrites the whole document.** A row wider than about 2 kB is compressed or moved out of line (TOAST), and an `UPDATE` "incurs no TOAST costs if none of the out-of-line values change" ([TOAST](https://www.postgresql.org/docs/18/storage-toast.html)). Changing one key changes the value: a `jsonb_set` on one key of an 87 KiB document grew the TOAST table from 96 KiB to 184 KiB, because the whole value was written again (checked). Move hot counters and status fields out of large documents into columns or a child table.
- **Select the keys or columns needed, not the whole document.** "The big values of TOASTed attributes will only be pulled out (if selected at all) at the time the result set is sent to the client" ([TOAST](https://www.postgresql.org/docs/18/storage-toast.html)). `SELECT *` or `SELECT doc` pulls out and ships every large document; `SELECT id, doc ->> 'status'` sends one key per row.
- **Validate shape with `CHECK`, and remember NULL passes.** A check constraint "is satisfied if the check expression evaluates to true or the null value" ([check constraints](https://www.postgresql.org/docs/18/ddl-constraints.html#DDL-CONSTRAINTS-CHECK-CONSTRAINTS)). `doc @@ '$.qty'` is NULL when `qty` is not a boolean, so that check accepts anything (checked). Write predicates that return true or false, and add `NOT NULL` to the column.

```sql
CREATE TABLE orders (
  id  bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
  doc jsonb NOT NULL
    CHECK (jsonb_typeof(doc) = 'object')
    CHECK (doc ? 'ref' AND jsonb_typeof(doc -> 'ref') = 'string')
    CHECK (doc @@ '$.qty.type() == "number"')
);
```

- **`IS JSON OBJECT` also works as a check** on a jsonb column (`CHECK (doc IS JSON OBJECT)`), and `IS JSON ... WITH UNIQUE KEYS` checks text input for duplicate keys before it is cast ([IS JSON](https://www.postgresql.org/docs/18/functions-json.html#FUNCTIONS-SQLJSON-MISC)). For a `jsonb` column duplicates are already gone, so `WITH UNIQUE KEYS` checks nothing there.
- **Numbers become `numeric`; clients may not keep them.** `jsonb` rejects numbers outside `numeric` range, disallows `NaN` and infinity, and prints `1.230e-5` as `0.00001230`. The manual warns that systems reading JSON numbers as IEEE 754 doubles lose precision ([JSON types](https://www.postgresql.org/docs/18/datatype-json.html#JSON-TYPE-MAPPING-TABLE)); pgx decoding into `map[string]any` turned `12345678901234567890` into `1.2345678901234567e+19` (see `drivers.md`). Store identifiers and money that must round-trip exactly as JSON strings, or as columns.
- **`\u0000` is rejected.** `jsonb` input refuses `\u0000` and Unicode escapes the database encoding cannot represent ([JSON types](https://www.postgresql.org/docs/18/datatype-json.html)). Clean such input before it reaches the database, or the insert fails.

## Sources

- JSON types, design, type mapping, PostgreSQL 18: <https://www.postgresql.org/docs/18/datatype-json.html> (checked 2026-10-27)
- Constraints (check, foreign keys), PostgreSQL 18: <https://www.postgresql.org/docs/18/ddl-constraints.html> (checked 2026-10-27)
- Generated columns, PostgreSQL 18: <https://www.postgresql.org/docs/18/ddl-generated-columns.html> (checked 2026-10-27)
- TOAST, PostgreSQL 18: <https://www.postgresql.org/docs/18/storage-toast.html> (checked 2026-10-27)
- IS JSON, PostgreSQL 18: <https://www.postgresql.org/docs/18/functions-json.html#FUNCTIONS-SQLJSON-MISC> (checked 2026-10-27)
- Behaviour marked "checked" was run on PostgreSQL 18.6 (2026-10-27).
