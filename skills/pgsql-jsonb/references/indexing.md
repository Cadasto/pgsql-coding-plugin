# Indexing jsonb

Read when: a query filters on a jsonb column and is slow or planned as a sequential scan; a `CREATE INDEX` names a jsonb column or a JSON expression; choosing between `jsonb_ops` and `jsonb_path_ops`; an index on a JSON key "is not used"; row estimates for a JSON filter are far off.

Deterministic backstop: `EXPLAIN (ANALYZE, BUFFERS)` on the real query. Compare the rows the `Bitmap Index Scan` returns with `Rows Removed by Index Recheck`: when the index returns nearly every row, it is not narrowing anything. Reading the rest of the plan belongs to `pgsql-performance`; general index design (column order, partial indexes, `CONCURRENTLY`) belongs to `pgsql-indexing`.

## Contents

- Predicate shape decides the index
- Choosing the GIN operator class
- B-tree expression indexes on a key
- Generated columns
- Statistics and estimates
- Parameters keep the index

## Predicate shape decides the index

An index serves an operator, not a function, and only when the indexed expression appears exactly as written ([index types](https://www.postgresql.org/docs/18/indexes-types.html), [jsonb indexing](https://www.postgresql.org/docs/18/datatype-json.html#JSON-INDEXING)). Checked on PostgreSQL 18.6 with 200,000 rows:

| Predicate | GIN `jsonb_ops` on `doc` | GIN `jsonb_path_ops` on `doc` | B-tree on `(doc ->> 'k')` |
|---|---|---|---|
| `doc @> '{"k":"v"}'` | yes | yes | no |
| `doc ? 'k'`, `?\|`, `?&` | yes | no | no |
| `doc @? '$.k ? (@ == "v")'`, `doc @@ '$.k == "v"'` | yes | yes | no |
| `doc @? '$.n ? (@ > 9)'` (range) | scans the whole index | scans the whole index | no |
| `doc @? '$.k'` (key only) | scans the whole index | scans the whole index | no |
| `doc ->> 'k' = 'v'` | no | no | yes |
| `doc -> 'k' = '"v"'`, `doc['k'] = '"v"'` | no | no | no |
| `doc -> 'tags' ? 'x'` | no (needs a GIN index on `(doc -> 'tags')`) | no | no |
| `jsonb_path_exists(doc, ...)`, `JSON_EXISTS(doc, ...)`, `jsonb_exists(doc, 'k')` | no | no | no |

- **Write the indexable operator, not the function.** `jsonb_path_exists`, `JSON_EXISTS` and `jsonb_exists` compute the same answers as `@?` and `?` but never use a GIN index (checked on 18.6). Rewrite `WHERE JSON_EXISTS(doc, '$.tags[*] ? (@ == "vip")')` as `WHERE doc @? '$.tags[*] ? (@ == "vip")'` or `WHERE doc @> '{"tags":["vip"]}'`.
- **Only `accessor == constant` narrows a jsonpath search.** "A GIN index extracts clauses of the form `accessors_chain == constant` out of the jsonpath pattern" ([jsonb indexing](https://www.postgresql.org/docs/18/datatype-json.html#JSON-INDEXING)). A range filter or a bare key path still shows an `Index Cond`, but the index returned all 200,000 rows and the recheck threw 199,800 away (checked on 18.6). Use `?` for key existence and a B-tree expression index for ranges.
- **Index a nested path when queries always go through it.** `doc -> 'tags' ? 'vip'` needs `CREATE INDEX ON t USING GIN ((doc -> 'tags'))`; targeted expression indexes "are likely to be smaller and faster to search than a simple index" ([jsonb indexing](https://www.postgresql.org/docs/18/datatype-json.html#JSON-INDEXING)).

## Choosing the GIN operator class

- **Default `jsonb_ops` supports `?`, `?|`, `?&`, `@>`, `@?` and `@@`; `jsonb_path_ops` drops the key-exists operators** ([jsonb indexing](https://www.postgresql.org/docs/18/datatype-json.html#JSON-INDEXING)). Pick `jsonb_path_ops` when the queries are containment and `==` jsonpath only: it is "usually much smaller" and more specific (14 MB against 21 MB on the 18.6 test table).
- **`jsonb_path_ops` cannot find empty structures.** It "produces no index entries for JSON structures not containing any values, such as `{"a": {}}`", so `doc @> '{"tags": []}'` became a full-index scan returning every row (checked on 18.6). `jsonb_path_ops` also does not support the `.*` and `.**` accessors in jsonpath.
- **Do not keep both on one column without a reason.** "Inserting or updating one heap row can cause many inserts into the index (one for each key extracted from the indexed item)" ([GIN fast update](https://www.postgresql.org/docs/18/gin.html#GIN-FAST-UPDATE)), and a second GIN index doubles that work; drop the one no query uses.
- **B-tree and hash on a whole jsonb value only help equality of complete documents** ([jsonb indexing](https://www.postgresql.org/docs/18/datatype-json.html#JSON-INDEXING)).

## B-tree expression indexes on a key

- **Equality and ranges on one key need a B-tree expression index.** Index exactly the expression the query uses, including the cast:

```sql
CREATE INDEX events_status_idx ON events ((doc ->> 'status'));
CREATE INDEX events_amount_idx ON events (((doc ->> 'amount')::numeric));
-- served:     WHERE doc ->> 'status' = 'open'
-- served:     WHERE (doc ->> 'amount')::numeric > 99
-- not served: WHERE doc ->> 'amount' = '99.9'   (text, not numeric)
```

- **Index expressions must be immutable** ([CREATE INDEX](https://www.postgresql.org/docs/18/sql-createindex.html)). `->>`, casts to `numeric` and `JSON_VALUE(doc, '$.k')` qualify; `JSON_VALUE` indexes work when the query repeats the same `JSON_VALUE` call (checked on 18.6). The `jsonb_path_*_tz` functions are STABLE and cannot be indexed ([SQL/JSON path](https://www.postgresql.org/docs/18/functions-json.html#FUNCTIONS-SQLJSON-PATH)).
- **Pick one spelling per key and use it everywhere.** An index on `(doc ->> 'status')` does not serve `JSON_VALUE(doc, '$.status')`, `doc -> 'status'` or `doc['status']` (checked on 18.6).
- **Expression indexes cost writes.** They are computed "for each row insertion and non-HOT update" ([indexes on expressions](https://www.postgresql.org/docs/18/indexes-expressional.html)).

## Generated columns

- **Promote a filtered key to a `STORED` generated column.** It gives queries a typed column, a plain B-tree index and ordinary column statistics, and it stays in step with the document ([generated columns](https://www.postgresql.org/docs/18/ddl-generated-columns.html)). Write `STORED` explicitly; `pgsql-schema` explains why the PostgreSQL 18 default does not work here. Indexing the expression directly is the alternative when no column is wanted.

```sql
ALTER TABLE events
  ADD COLUMN customer_id bigint GENERATED ALWAYS AS ((doc ->> 'customer_id')::bigint) STORED;
CREATE INDEX events_customer_id_idx ON events (customer_id);
```

## Statistics and estimates

- **Without statistics the planner guesses.** For an expression it has no statistics on, equality is assumed to have 0.5% selectivity ([CREATE STATISTICS](https://www.postgresql.org/docs/18/sql-createstatistics.html)): on the test table `doc ->> 'status' = 'open'` was estimated at 1,000 rows and returned 50,000. A one-sided range is assumed to match about a third: `(doc ->> 'amount')::numeric > 99` was estimated at 66,667 of 200,000 rows and returned 1,800 (checked on 18.6). Bad estimates choose bad joins.
- **Run `ANALYZE` after creating an expression index.** "For new expression indexes, it is necessary to run ANALYZE or wait for the autovacuum daemon" ([CREATE INDEX](https://www.postgresql.org/docs/18/sql-createindex.html)). After it, the same estimates were 50,087 and 1,967.
- **Use expression statistics when an index is not wanted.** `CREATE STATISTICS s ON ((doc ->> 'status')) FROM events` gives the planner the distribution "without the overhead of index maintenance"; list two expressions to capture their correlation ([CREATE STATISTICS](https://www.postgresql.org/docs/18/sql-createstatistics.html)).

## Parameters keep the index

- **Bind the value, keep the operator.** With a forced generic plan, `doc @> $1`, `doc @> jsonb_build_object('status', $1)` and `doc @? $1::jsonpath` all kept the GIN index (checked on 18.6). Prefer `@>` with a bound jsonb or `jsonb_build_object`: a jsonpath assembled from user strings can be injected into, and `jsonb_path_exists(doc, path, vars)` loses the index.

## Sources

- jsonb indexing, PostgreSQL 18: <https://www.postgresql.org/docs/18/datatype-json.html#JSON-INDEXING> (checked 2026-10-27)
- Index types, PostgreSQL 18: <https://www.postgresql.org/docs/18/indexes-types.html> (checked 2026-10-27)
- Indexes on expressions, PostgreSQL 18: <https://www.postgresql.org/docs/18/indexes-expressional.html> (checked 2026-10-27)
- CREATE INDEX (immutability, statistics for expression indexes): <https://www.postgresql.org/docs/18/sql-createindex.html> (checked 2026-10-27)
- CREATE STATISTICS (expression statistics, default 0.5% equality selectivity): <https://www.postgresql.org/docs/18/sql-createstatistics.html> (checked 2026-10-27)
- GIN indexes, fast update (one index insert per extracted key): <https://www.postgresql.org/docs/18/gin.html#GIN-FAST-UPDATE> (checked 2026-10-27)
- Generated columns, PostgreSQL 18: <https://www.postgresql.org/docs/18/ddl-generated-columns.html> (checked 2026-10-27)
- SQL/JSON path, `_tz` functions: <https://www.postgresql.org/docs/18/functions-json.html#FUNCTIONS-SQLJSON-PATH> (checked 2026-10-27)
- Behaviour marked "checked on 18.6" was run on PostgreSQL 18.6 with a 200,000-row table (2026-10-27).
