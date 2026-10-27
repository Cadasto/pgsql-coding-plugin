---
type: llm
weight: 2
---

PASS if the rewritten WHERE clause filters both conditions on the bare `doc` column with an operator that a `jsonb_path_ops` GIN index supports: `@>` containment (for example `doc @> $1` with a Go map or struct holding `customer_id` and `tags: ["vip"]`, or `doc @> jsonb_build_object(...)`), or `@?` / `@@` with `==` comparisons; AND `customer_id` is bound as a parameter and reaches the database as a JSON number (an `int64` in a map, or `$1::bigint` inside `jsonb_build_object`), not as a JSON string; AND no value is formatted into the SQL or jsonpath text with `fmt.Sprintf` or concatenation.
FAIL if either condition still uses `->>` equality, `jsonb_path_exists`, `JSON_EXISTS` or `jsonb_exists` as its only filter; if it uses the `?`, `?|` or `?&` operators (which `jsonb_path_ops` does not support); if `customer_id` is sent as a JSON string such as `"42"`; or if it proposes a different index instead of a predicate the existing index can serve.
