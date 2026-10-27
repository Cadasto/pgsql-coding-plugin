---
name: pgsql-indexing
description: This skill should be used when a task creates, reviews, or questions a PostgreSQL index, or asks why a query ignores one, for example CREATE INDEX, a composite or multicolumn index and its column order, INCLUDE for a covering index, a partial index with WHERE, an expression index such as lower(email), UNIQUE NULLS NOT DISTINCT, text_pattern_ops or COLLATE "C" for LIKE 'abc%', pg_trgm gin_trgm_ops for ILIKE '%term%', GIN, GiST, SP-GiST, BRIN or hash, an index-only scan, skip scan, an index on a foreign-key column, fillfactor and HOT updates, unused, duplicate or invalid indexes in pg_stat_user_indexes or pg_index, index bloat and when to REINDEX, or a HypoPG what-if test. PostgreSQL 18, with 19 as hints. Not for reading EXPLAIN plans (pgsql-performance), jsonb operator classes (pgsql-jsonb), or building and rebuilding indexes on a live table (pgsql-migrations).
---

# pgsql-indexing: PostgreSQL index design and upkeep

Choosing, writing and maintaining indexes on PostgreSQL 18: the index type, column order, partial, expression and covering indexes, and the evidence for adding or dropping one.

Deterministic backstop: `EXPLAIN (ANALYZE, BUFFERS)` on production-like data, after `ANALYZE`, decides whether an index is used (read the plan with `pgsql-performance`); `squawk` flags a non-concurrent index build in a migration; the catalog queries in [maintenance.md](references/maintenance.md) find unused, duplicate, invalid and missing foreign-key indexes.

## Rules

- **Prove the need on real data.** Run `ANALYZE` first and test with production-like volumes; the manual calls very small test data sets "especially fatal" to index decisions ([examining index usage](https://www.postgresql.org/docs/18/indexes-examine.html)).
- **Equality columns first, then the range or sort column.** Equality on the leading columns, plus one inequality on the first column without equality, limits the part of a B-tree that is read; later columns only filter ([multicolumn indexes](https://www.postgresql.org/docs/18/indexes-multicolumn.html)). `WHERE customer_id = $1 ORDER BY created_at DESC LIMIT 20` wants `(customer_id, created_at)`.
- **Skip scan is not a reason to put a selective column second.** PostgreSQL 18 can skip through a leading column that has no condition, but only pays off when that column has few distinct values; check the `Index Searches` line of `EXPLAIN ANALYZE` ([multicolumn indexes](https://www.postgresql.org/docs/18/indexes-multicolumn.html), [using EXPLAIN](https://www.postgresql.org/docs/18/using-explain.html)).
- **Keep composite indexes short.** "Indexes with more than three columns are unlikely to be helpful unless the usage of the table is extremely stylized" ([multicolumn indexes](https://www.postgresql.org/docs/18/indexes-multicolumn.html)).
- **Prefix `LIKE` needs `text_pattern_ops` or a `"C"` collation in a non-C database.** A default-operator-class B-tree serves `<` and `>` but not `LIKE 'abc%'` there, and the pattern must be a constant at planning time, so a generic plan for `col LIKE $1 || '%'` cannot use the index ([index types](https://www.postgresql.org/docs/18/indexes-types.html), [operator classes](https://www.postgresql.org/docs/18/indexes-opclass.html)); generic plans belong to `pgsql-performance`.
- **Infix and case-insensitive search uses `pg_trgm`.** `USING gin (col gin_trgm_ops)` serves `LIKE`, `ILIKE`, `~` and `~*` with leading wildcards; a pattern with no extractable trigrams degrades to a full index scan ([pg_trgm](https://www.postgresql.org/docs/18/pgtrgm.html)).
- **Write a partial index predicate into the query as a literal.** The planner matches it at planning time and only proves simple implications, so `WHERE status = $1` never uses an index declared `WHERE status = 'active'` under a generic plan ([partial indexes](https://www.postgresql.org/docs/18/indexes-partial.html)).
- **An expression index needs the same expression in the query and only IMMUTABLE functions.** `created_at::date` on `timestamptz` is rejected; index and query `(created_at AT TIME ZONE 'UTC')::date` instead ([CREATE INDEX](https://www.postgresql.org/docs/18/sql-createindex.html), [function volatility](https://www.postgresql.org/docs/18/xfunc-volatility.html)).
- **Add `INCLUDE` columns sparingly.** They pay off only for index-only scans on tables that change slowly enough for the visibility map to stay set; wide payloads bloat the index and can fail inserts ([index-only scans](https://www.postgresql.org/docs/18/indexes-index-only-scans.html)).
- **Match a mixed `ORDER BY` with the index direction.** `ORDER BY x, y DESC` needs `(x, y DESC)` or `(x DESC, y)`; only B-tree returns sorted rows ([indexes and ORDER BY](https://www.postgresql.org/docs/18/indexes-ordering.html)).
- **Index the referencing columns of a foreign key.** PostgreSQL does not create that index, and every `DELETE` or key `UPDATE` on the parent scans the child for matches ([constraints](https://www.postgresql.org/docs/18/ddl-constraints.html)). A composite index that leads with those columns counts.
- **Choose NULL semantics for uniqueness on purpose.** `UNIQUE NULLS NOT DISTINCT` allows one NULL; a partial unique index enforces "one active row per key" ([constraints](https://www.postgresql.org/docs/18/ddl-constraints.html), [partial indexes](https://www.postgresql.org/docs/18/indexes-partial.html)).
- **Every index costs writes.** Each one is kept in sync on every write and can prevent HOT updates; drop indexes that are seldom or never used ([introduction](https://www.postgresql.org/docs/18/indexes-intro.html), [HOT](https://www.postgresql.org/docs/18/storage-hot.html)).
- **Building or rebuilding an index on a table that takes writes belongs to `pgsql-migrations`.** A plain `CREATE INDEX` blocks inserts, updates and deletes until it ends ([introduction](https://www.postgresql.org/docs/18/indexes-intro.html)); this skill finds the INVALID index a failed build leaves behind ([maintenance.md](references/maintenance.md)).
- **Pick the type by operator.** B-tree for comparisons and sorting, GIN for "contains" on arrays and full text, GiST for ranges, geometry and nearest-neighbour, BRIN for huge tables in physical order ([index types](https://www.postgresql.org/docs/18/indexes-types.html)). jsonb operator classes belong to `pgsql-jsonb`.

## Read the reference

| The task involves | Read |
|---|---|
| choosing GIN, GiST, SP-GiST, BRIN or hash; `pg_trgm`; pattern operator classes; collations; full-text search indexes | [types.md](references/types.md) |
| column order, skip scan, `OR` conditions, partial, expression or covering indexes, index-only scans, sort order, unique and NULL handling, foreign keys, write cost and fillfactor | [design.md](references/design.md) |
| unused, duplicate, redundant, invalid or missing foreign-key indexes, bloat, collation version changes, HypoPG | [maintenance.md](references/maintenance.md) |

## Sources

- PostgreSQL 18 manual, chapter 11 Indexes: <https://www.postgresql.org/docs/18/indexes.html>
- `CREATE INDEX`: <https://www.postgresql.org/docs/18/sql-createindex.html>; `REINDEX`: <https://www.postgresql.org/docs/18/sql-reindex.html>
- PostgreSQL 18 release notes (skip scan, `OR` to arrays, parallel GIN builds): <https://www.postgresql.org/docs/18/release-18.html>
- `pg_trgm`: <https://www.postgresql.org/docs/18/pgtrgm.html>
- Reference files list their own sources.
