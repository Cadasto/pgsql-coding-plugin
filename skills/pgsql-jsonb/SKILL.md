---
name: pgsql-jsonb
description: This skill should be used when SQL reads, writes, filters, indexes or validates json or jsonb, for example the `->`, `->>`, `#>>`, `@>`, `?`, `?|`, `@?` or `@@` operators, jsonb subscripting, jsonb_set, jsonb_set_lax, jsonb_agg, jsonb_object_agg, jsonb_to_recordset, JSON_VALUE, JSON_QUERY, JSON_EXISTS, JSON_TABLE, JSON_OBJECT, IS JSON, jsonpath in lax or strict mode, a GIN index with jsonb_ops or jsonb_path_ops, an expression or generated column on a JSON key, a slow query or bad row estimate on a jsonb filter, a CHECK on document shape, or jsonb passed through pgx or PDO. PostgreSQL 18, with 19 additions as hints. Not for general index design (`pgsql-indexing`), reading a query plan (`pgsql-performance`), table design outside the document (`pgsql-schema`), or plain parameter binding (`pgsql-query`).
---

# pgsql-jsonb: JSON and jsonb in PostgreSQL 18

Scope: the jsonb type, its operators and functions, SQL/JSON and jsonpath, indexing documents, modelling documents, and jsonb at the pgx and PDO boundary.

Deterministic backstop: none checks JSON SQL statically. Run the query in `psql` against PostgreSQL 18, and run `EXPLAIN (ANALYZE, BUFFERS)` to see whether an index is used and how many rows it returns. Rules marked "checked on 18.6" in the references were run on PostgreSQL 18.6.

## Rules

- **Store `jsonb`.** It is "significantly faster to process" and indexable; keep `json` only when key order or duplicate keys must survive ([JSON types](https://www.postgresql.org/docs/18/datatype-json.html)).
- **Write the operator the index serves.** A GIN index on `doc` serves `@>`, `?`, `?|`, `?&`, `@?` and `@@`. It never serves `doc ->> 'k' = 'v'`, `jsonb_path_exists()`, `JSON_EXISTS()` or `jsonb_exists()`, and `doc -> 'tags' ? 'x'` needs its own index on `(doc -> 'tags')` ([jsonb indexing](https://www.postgresql.org/docs/18/datatype-json.html#JSON-INDEXING)). The per-shape table is in `indexing.md`.
- **Pick the GIN operator class from the operators in use.** `jsonb_path_ops` is smaller and more specific but has no `?`, `?|` or `?&`, and cannot find empty structures such as `{"tags": []}` without scanning the whole index ([jsonb indexing](https://www.postgresql.org/docs/18/datatype-json.html#JSON-INDEXING)).
- **Only `accessor == constant` narrows a jsonpath index search.** `doc @? '$.n ? (@ > 9)'` and a bare `doc @? '$.k'` show an index condition but read every entry. Use `?` for key existence and a B-tree expression index for ranges ([jsonb indexing](https://www.postgresql.org/docs/18/datatype-json.html#JSON-INDEXING)).
- **Index the exact expression the query writes, then `ANALYZE`.** An index on `((doc ->> 'amount')::numeric)` serves that cast and nothing else. Without statistics on the expression the planner assumes 0.5% selectivity for equality ([CREATE STATISTICS](https://www.postgresql.org/docs/18/sql-createstatistics.html)) and about a third for a one-sided range (checked on 18.6); `ANALYZE` after creating the index fixes both ([CREATE INDEX](https://www.postgresql.org/docs/18/sql-createindex.html)).
- **Promote a filtered key to a `STORED` generated column.** `GENERATED ALWAYS AS ((doc ->> 'k')::bigint) STORED` plus a B-tree index gives a typed, indexed copy that stays in step with the document; `pgsql-schema` explains why it must be `STORED` ([generated columns](https://www.postgresql.org/docs/18/ddl-generated-columns.html)).
- **Keep the two nulls apart.** `->` returns JSON `null` for a null value and SQL NULL for a missing key; `->>` returns SQL NULL for both. `jsonb_set` with an SQL NULL value returns NULL for the whole document, so use `jsonb_set_lax` ([processing functions](https://www.postgresql.org/docs/18/functions-json.html#FUNCTIONS-JSON-PROCESSING-TABLE)).
- **Compare jsonb with jsonb, text with text.** `doc['k'] = '"v"'` or `doc ->> 'k' = 'v'`. Cast numbers from `->>`; casting a JSON string with `(doc -> 'n')::int` raises an error ([jsonb subscripting](https://www.postgresql.org/docs/18/datatype-json.html#JSONB-SUBSCRIPTING)).
- **Know what fails silently.** `jsonb_set` returns the target unchanged when a parent key is missing, and `||` replaces nested objects instead of merging them. `JSON_VALUE` and `JSON_QUERY` return NULL on error, and `JSON_TABLE` returns zero rows, unless `ERROR ON ERROR` is written ([SQL/JSON query functions](https://www.postgresql.org/docs/18/functions-json.html#SQLJSON-QUERY-FUNCTIONS)).
- **Build a JSON array as `COALESCE(jsonb_agg(x ORDER BY x), '[]')`.** `COALESCE` turns the NULL of an aggregate over zero rows into `[]` (the NULL rule is `pgsql-query`'s); `ORDER BY` goes inside the call because input order is unspecified ([aggregate functions](https://www.postgresql.org/docs/18/functions-aggregate.html)).
- **Use strict jsonpath when a missing key is a bug.** Lax mode, the default, unwraps arrays and turns structural errors into "no match" ([strict and lax modes](https://www.postgresql.org/docs/18/functions-json.html#FUNCTIONS-SQLJSON-STRICT-AND-LAX-MODES)). The `_tz` path functions are STABLE and cannot be indexed.
- **Keep updated documents small and promote what the database enforces.** Any update locks the whole row and rewrites the whole stored value ([designing JSON documents](https://www.postgresql.org/docs/18/datatype-json.html#JSON-DOC-DESIGN), [TOAST](https://www.postgresql.org/docs/18/storage-toast.html)). Keys that need a foreign key, `UNIQUE`, `NOT NULL`, joins or range filters belong in columns.
- **A CHECK that evaluates to NULL passes.** `CHECK (doc @@ '$.qty')` accepts any `qty` that is not a boolean. Write predicates that yield true or false, and declare the column `NOT NULL` ([check constraints](https://www.postgresql.org/docs/18/ddl-constraints.html#DDL-CONSTRAINTS-CHECK-CONSTRAINTS)).
- **pgx sends a Go `string` or `[]byte` as JSON text and marshals everything else.** A plain Go string that is not JSON fails, and `map[string]any` decodes big numbers to `float64`. A struct used as an `@>` filter sends its zero values ([pgx `pgtype/json.go`](https://github.com/jackc/pgx/blob/v5.11.0/pgtype/json.go)).
- **In PDO, escape the `?` operators as `??`.** Do not swap `?` for `jsonb_exists()`, which loses the index ([PDO::prepare](https://www.php.net/manual/en/pdo.prepare.php)).

## Read the reference

| The task involves | Read |
|---|---|
| an operator, a cast, NULL handling, `jsonb_set`, `\|\|`, building or aggregating JSON, expanding to rows, `JSON_VALUE`, `JSON_QUERY`, `JSON_EXISTS`, `JSON_TABLE`, jsonpath, PostgreSQL 19 JSON changes | [functions.md](references/functions.md) |
| a GIN or expression index on jsonb, an index not used, `jsonb_ops` against `jsonb_path_ops`, row estimates on a JSON filter, a generated column to index | [indexing.md](references/indexing.md) |
| `json` against `jsonb`, document or column, generated columns, large or hot documents, TOAST, `CHECK` on shape, numbers and precision | [modeling.md](references/modeling.md) |
| pgx encoding and scanning of jsonb, simple protocol, PDO `?` operators, binding a document from PHP | [drivers.md](references/drivers.md) |

## Sources

- JSON types, PostgreSQL 18: <https://www.postgresql.org/docs/18/datatype-json.html>
- JSON functions and operators, PostgreSQL 18: <https://www.postgresql.org/docs/18/functions-json.html>
- Aggregate functions, PostgreSQL 18: <https://www.postgresql.org/docs/18/functions-aggregate.html>
- CREATE INDEX and CREATE STATISTICS, PostgreSQL 18: <https://www.postgresql.org/docs/18/sql-createindex.html>, <https://www.postgresql.org/docs/18/sql-createstatistics.html>
- Generated columns, constraints, TOAST, PostgreSQL 18: <https://www.postgresql.org/docs/18/ddl-generated-columns.html>, <https://www.postgresql.org/docs/18/ddl-constraints.html>, <https://www.postgresql.org/docs/18/storage-toast.html>
- pgx v5.11.0 JSON codec: <https://github.com/jackc/pgx/blob/v5.11.0/pgtype/json.go>
- PHP manual, PDO::prepare: <https://www.php.net/manual/en/pdo.prepare.php>
