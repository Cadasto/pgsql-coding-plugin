# jsonb operators, functions, SQL/JSON and jsonpath

Read when: a query extracts, compares, casts, modifies, builds, aggregates or expands JSON; uses `->`, `->>`, `#>`, `#>>`, `@>`, `?`, `||`, `-`, `#-`, `@?`, `@@` or subscripting; calls `jsonb_set`, `jsonb_set_lax`, `jsonb_insert`, `jsonb_strip_nulls`, `jsonb_agg`, `jsonb_object_agg`, `jsonb_each`, `jsonb_array_elements`, `jsonb_to_recordset`, `jsonb_populate_record`, `JSON_OBJECT`, `JSON_ARRAY`, `JSON_ARRAYAGG`, `JSON_OBJECTAGG`, `JSON_VALUE`, `JSON_QUERY`, `JSON_EXISTS`, `JSON_TABLE` or a `jsonb_path_*` function.

Deterministic backstop: none. Run the expression in `psql` against PostgreSQL 18 and look at the result; check index use with `EXPLAIN` (see `indexing.md`).

## Contents

- Extracting and comparing
- SQL NULL versus JSON null
- Modifying documents
- Building JSON and aggregating
- Expanding JSON into rows
- SQL/JSON query functions and JSON_TABLE
- jsonpath
- Newer in PostgreSQL 19 (hints)

## Extracting and comparing

- **`->` returns jsonb, `->>` returns text.** Both return SQL NULL when the key or element is missing, "rather than failing" ([JSON operators](https://www.postgresql.org/docs/18/functions-json.html#FUNCTIONS-JSON-OP-TABLE)). `#>` and `#>>` take a `text[]` path. Array indexes start at zero; a negative index counts from the end.
- **Compare jsonb with jsonb.** Subscripting and `->` return jsonb, so the literal must be a JSON value: `doc['status'] = '"open"'`, not `= 'open'` ([jsonb subscripting](https://www.postgresql.org/docs/18/datatype-json.html#JSONB-SUBSCRIPTING)). To compare with text, use `->>`.
- **Cast numbers from text, not from a JSON string.** `(doc -> 'n')::int` works for a JSON number but raises `cannot cast jsonb string to type integer` when the value is `"5"`; `(doc ->> 'n')::int` works for both (checked). Since 18, a JSON `null` casts to SQL NULL instead of raising ([release notes 18](https://www.postgresql.org/docs/18/release-18.html)).
- **`@>` is structural.** The right side must match structure and data, array order does not matter, and nesting must line up: `'{"a":{"b":1}}' @> '{"b":1}'` is false ([containment](https://www.postgresql.org/docs/18/datatype-json.html#JSON-CONTAINMENT)).
- **`?`, `?|` and `?&` look at the top level only.** They match an object key or a string array element, never a value and never a nested key: `'{"a":{"b":1}}' ? 'b'` is false ([containment and existence](https://www.postgresql.org/docs/18/datatype-json.html#JSON-CONTAINMENT)).

## SQL NULL versus JSON null

- **Two nulls exist.** `'{"a":null}'::jsonb -> 'a'` is the JSON value `null` (not SQL NULL); `->> 'a'` is SQL NULL, the same as for a missing key (checked). `jsonb_typeof` returns the text `'null'` for a JSON null and SQL NULL for SQL NULL input ([processing functions](https://www.postgresql.org/docs/18/functions-json.html#FUNCTIONS-JSON-PROCESSING-TABLE)). Test presence with `?` and the value with `->>`, not one with the other.
- **`jsonb_set` with an SQL NULL value returns NULL for the whole document.** An `UPDATE ... SET doc = jsonb_set(doc, '{k}', to_jsonb($1))` with a NULL parameter wipes the column. Use `jsonb_set_lax`, whose default `null_value_treatment` is `'use_json_null'`; the other choices are `'raise_exception'`, `'delete_key'` and `'return_target'` ([processing functions](https://www.postgresql.org/docs/18/functions-json.html#FUNCTIONS-JSON-PROCESSING-TABLE)).

## Modifying documents

- **`jsonb_set` does not create missing parents.** "All earlier steps in the path must exist, or the target is returned unchanged": `jsonb_set('{"a":{}}', '{x,y}', '1')` silently returns `{"a": {}}` ([processing functions](https://www.postgresql.org/docs/18/functions-json.html#FUNCTIONS-JSON-PROCESSING-TABLE)). Subscripted assignment does create them: `SET doc['x']['y'] = '1'` builds empty objects on the way, pads arrays with nulls, and raises an error if an intermediate value is a scalar ([jsonb subscripting](https://www.postgresql.org/docs/18/datatype-json.html#JSONB-SUBSCRIPTING)).
- **`||` merges the top level only.** `'{"a":{"x":1}}' || '{"a":{"y":2}}'` gives `{"a": {"y": 2}}`; the nested object is replaced, not merged ([jsonb operators](https://www.postgresql.org/docs/18/functions-json.html#FUNCTIONS-JSONB-OP-TABLE)). Merge a nested object with `jsonb_set(doc, '{a}', (doc -> 'a') || $1)`.
- **Delete with `-` and `#-`.** `doc - 'k'` drops a key, `doc - '{a,b}'::text[]` drops several, `doc #- '{a,b}'` drops a nested path. `doc - 1` on a non-array raises an error ([jsonb operators](https://www.postgresql.org/docs/18/functions-json.html#FUNCTIONS-JSONB-OP-TABLE)).
- **`jsonb_insert` inserts, `jsonb_set` replaces.** `jsonb_insert` adds to an object only when the key is absent and shifts array elements; `jsonb_strip_nulls(doc, true)` (the second argument is new in 18) also drops null array elements ([processing functions](https://www.postgresql.org/docs/18/functions-json.html#FUNCTIONS-JSON-PROCESSING-TABLE), [release notes 18](https://www.postgresql.org/docs/18/release-18.html)).

## Building JSON and aggregating

- **Wrap `JSON_ARRAYAGG` in `COALESCE` too.** Over zero rows it gives SQL NULL, not `[]`, like `jsonb_agg` (SKILL.md) and every aggregate but `count` ([aggregate functions](https://www.postgresql.org/docs/18/functions-aggregate.html)).
- **Order is unspecified unless stated.** Put `ORDER BY` inside the aggregate call for `jsonb_agg` and `jsonb_object_agg` ([aggregate functions](https://www.postgresql.org/docs/18/functions-aggregate.html)); filter with `FILTER (WHERE ...)`.
- **The NULL defaults differ by function** (checked): `json_array(...)` and `JSON_ARRAYAGG` drop NULLs (ABSENT ON NULL); `json_object(...)` and `JSON_OBJECTAGG` keep them (NULL ON NULL); `jsonb_agg` keeps them. State `ABSENT ON NULL` or `NULL ON NULL`, or use `jsonb_agg_strict`, so the reader does not have to know.
- **Duplicate keys.** `jsonb_object_agg` keeps the last value for a repeated key; `jsonb_object_agg_unique` raises an error; the `_strict` forms skip NULL values ([aggregate functions](https://www.postgresql.org/docs/18/functions-aggregate.html)).
- **`JSON_OBJECT` and `JSON_ARRAY` return `json` unless told.** Add `RETURNING jsonb` when the result is stored or compared ([JSON creation functions](https://www.postgresql.org/docs/18/functions-json.html#FUNCTIONS-JSON-CREATION-TABLE)).

## Expanding JSON into rows

- **Use the record functions for typed rows.** `jsonb_to_recordset(doc -> 'items') AS t(sku text, qty int)` gives typed columns; missing keys become NULL ([processing functions](https://www.postgresql.org/docs/18/functions-json.html#FUNCTIONS-JSON-PROCESSING-TABLE)). Use `jsonb_array_elements` and `jsonb_each` in a `LATERAL` join when the shape varies. `JSON_TABLE` (below) covers nested arrays and error handling in one call.

```sql
SELECT o.id, i.sku, i.qty
FROM orders o
CROSS JOIN LATERAL jsonb_to_recordset(o.doc -> 'items') AS i(sku text, qty int);
```

## SQL/JSON query functions and JSON_TABLE

`JSON_EXISTS`, `JSON_QUERY`, `JSON_VALUE` and `JSON_TABLE` arrived in PostgreSQL 17 ([release notes 17](https://www.postgresql.org/docs/17/release-17.html)).

- **Errors and empty results are silent by default.** `JSON_VALUE` and `JSON_QUERY` return SQL NULL on error and on empty; `JSON_EXISTS` returns false on error ([SQL/JSON query functions](https://www.postgresql.org/docs/18/functions-json.html#SQLJSON-QUERY-FUNCTIONS)). Add `ERROR ON ERROR` (and `ERROR ON EMPTY`) where bad data must surface instead of turning into NULL.
- **`JSON_VALUE` is for one scalar.** It returns text by default, removes the quotes from a string, and treats an object, array or several items as an error, which by default becomes NULL. Use `JSON_QUERY` for objects and arrays; add `WITH CONDITIONAL WRAPPER` when the path may return several items ([SQL/JSON query functions](https://www.postgresql.org/docs/18/functions-json.html#SQLJSON-QUERY-FUNCTIONS)).
- **Use `RETURNING` to type the value.** `JSON_VALUE(doc, '$.amount' RETURNING numeric)` instead of a cast on text ([SQL/JSON query functions](https://www.postgresql.org/docs/18/functions-json.html#SQLJSON-QUERY-FUNCTIONS)).
- **Pass values with `PASSING`.** `JSON_EXISTS(doc, '$.tags[*] ? (@ == $t)' PASSING $1 AS t)` binds the value; never build the path from strings ([SQL/JSON query functions](https://www.postgresql.org/docs/18/functions-json.html#SQLJSON-QUERY-FUNCTIONS)).
- **`JSON_TABLE` returns zero rows on error by default.** A structural error in strict mode yields an empty table unless `ERROR ON ERROR` is written (checked). Number rows with `FOR ORDINALITY`; unnest child arrays with `NESTED PATH`; a column without `PATH` reads `$.column_name` ([JSON_TABLE](https://www.postgresql.org/docs/18/functions-json.html#FUNCTIONS-SQLJSON-TABLE)).

```sql
SELECT jt.*
FROM orders o,
     JSON_TABLE(o.doc, '$' COLUMNS (
       order_ref text PATH '$.ref',
       NESTED PATH '$.items[*]' COLUMNS (
         line FOR ORDINALITY,
         sku  text,
         qty  int PATH '$.qty' ERROR ON ERROR))) AS jt;
```

## jsonpath

- **Lax is the default and hides structural errors.** Lax mode unwraps arrays automatically and turns a missing key into "no match"; strict mode raises an error ([strict and lax modes](https://www.postgresql.org/docs/18/functions-json.html#FUNCTIONS-SQLJSON-STRICT-AND-LAX-MODES)). Use `strict` when a missing key is a bug. Use the `.**` accessor only in strict mode; in lax mode it can return the same item twice.
- **`@?` takes a path, `@@` takes a predicate.** `doc @? '$.a[*] ? (@ > 2)'` and `doc @@ '$.a[*] > 2'`. `@@` returns NULL when the path is not a single boolean ([jsonpath operators](https://www.postgresql.org/docs/18/functions-json.html#FUNCTIONS-JSONB-OP-TABLE)).
- **Use the `_tz` functions for time zone comparisons, and never in an index.** A `.datetime()` comparison that needs a time zone conversion raises an error in `jsonb_path_exists`; `jsonb_path_exists_tz` handles it but is STABLE, so it "cannot be used in indexes" ([SQL/JSON path](https://www.postgresql.org/docs/18/functions-json.html#FUNCTIONS-SQLJSON-PATH)).
- **Double backslashes in `like_regex`.** The pattern is a jsonpath string literal inside an SQL literal, and PostgreSQL uses its POSIX engine, not the standard `LIKE_REGEX` ([regular expression deviation](https://www.postgresql.org/docs/18/functions-json.html#FUNCTIONS-SQLJSON-REGULAR-EXPRESSION-DEVIATION)).

## Newer in PostgreSQL 19 (hints)

PostgreSQL 19 is a release candidate; these are not rules until a project runs it ([release notes 19](https://www.postgresql.org/docs/19/release-19.html)).

- `json_array()` over a query that returns no rows returns `[]` instead of NULL. Code relying on the NULL changes behaviour on upgrade.
- jsonpath gains `ltrim()`, `rtrim()`, `btrim()`, `lower()`, `upper()`, `initcap()`, `replace()` and `split_part()`, all immutable.
- `IS JSON` works on domains over `text`, `json`, `jsonb` and `bytea`.
- `COPY ... TO` can write JSON, optionally as one array with `FORCE_ARRAY`.

## Sources

- JSON functions and operators, PostgreSQL 18: <https://www.postgresql.org/docs/18/functions-json.html> (checked 2026-10-27)
- JSON types, containment, subscripting, PostgreSQL 18: <https://www.postgresql.org/docs/18/datatype-json.html> (checked 2026-10-27)
- Aggregate functions, PostgreSQL 18: <https://www.postgresql.org/docs/18/functions-aggregate.html> (checked 2026-10-27)
- Release notes 17 (SQL/JSON functions): <https://www.postgresql.org/docs/17/release-17.html> (checked 2026-10-27)
- Release notes 18 (jsonb null casts, `strip_in_arrays`): <https://www.postgresql.org/docs/18/release-18.html> (checked 2026-10-27)
- Release notes 19, as of 2026-10-09: <https://www.postgresql.org/docs/19/release-19.html> (checked 2026-10-27)
- Behaviour marked "checked" was run on PostgreSQL 18.6 (2026-10-27).
