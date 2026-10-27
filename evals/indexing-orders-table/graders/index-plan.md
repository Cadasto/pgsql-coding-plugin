---
type: llm
weight: 2
---

PASS if all of these hold:
- One B-tree index has `customer_id` as its first column and `created_at` as its second (either direction; extra `INCLUDE` columns are fine), and the answer says or makes clear that this index also serves the customer delete, because the foreign key's referencing column was unindexed.
- The index for query 3 uses `text_pattern_ops` (or `varchar_pattern_ops`), a `COLLATE "C"` column, or a `pg_trgm` operator class, and the answer ties this to the non-C `en_US.UTF-8` collation; a plain default-operator-class B-tree on `reference` does not count.
- Every `CREATE INDEX` uses `CONCURRENTLY` and none is wrapped in `BEGIN`/`COMMIT` or described as running inside one transaction.

FAIL if `created_at` leads `customer_id` in the index for query 1, if query 3 gets only a default B-tree on `reference`, if any index is built without `CONCURRENTLY`, if a concurrent build is placed inside a transaction block, or if a partial index for query 2 uses a predicate that the query's literal `status = 'pending'` does not imply.
