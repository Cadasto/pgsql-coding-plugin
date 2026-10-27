# Index types and operator classes

Read when: a task picks an index type (B-tree, hash, GIN, GiST, SP-GiST, BRIN), indexes text for `LIKE`, `ILIKE`, regular expressions or full-text search, adds `pg_trgm`, names an operator class such as `text_pattern_ops` or `gin_trgm_ops`, or indexes a column with a non-default collation.

Backstop: `EXPLAIN` shows whether the index is used; `\dAc` in psql, or the catalog query below, lists the operator classes the server has. jsonb operator classes (`jsonb_ops`, `jsonb_path_ops`) belong to `pgsql-jsonb`.

## Rules

- **B-tree is the default and the only type that returns sorted rows.** It serves `<`, `<=`, `=`, `>=`, `>`, `BETWEEN`, `IN`, `IS NULL` and `IS NOT NULL`, multicolumn keys, `UNIQUE`, `INCLUDE` and index-only scans ([index types](https://www.postgresql.org/docs/18/indexes-types.html), [ordering](https://www.postgresql.org/docs/18/indexes-ordering.html)). Choose another type only when the operator needs it.
- **Hash serves only `=`, on one column, without uniqueness.** It can be much smaller than a B-tree for long values such as URLs, and it is crash recoverable ([hash indexes](https://www.postgresql.org/docs/18/hash-index.html)). It cannot back a `UNIQUE` constraint, a range condition or an `ORDER BY`, so a B-tree stays the safer default.
- **GIN for "contains" on multi-valued columns.** Arrays (`&&`, `@>`, `<@`, `=`) and `tsvector` (`@@`) use GIN ([index types](https://www.postgresql.org/docs/18/indexes-types.html), [GIN operator classes](https://www.postgresql.org/docs/18/gin.html#GIN-BUILTIN-OPCLASSES)). Inserts are slow because one row adds many keys: for a bulk load, create the index afterwards, and give the build a generous `maintenance_work_mem` ([GIN tips](https://www.postgresql.org/docs/18/gin.html#GIN-TIPS)). PostgreSQL 18 builds GIN indexes in parallel ([release notes](https://www.postgresql.org/docs/18/release-18.html)).
- **Decide on the GIN pending list.** With `fastupdate` on (the default), new entries wait in an unsorted pending list that every search must also scan, and the insert that overflows `gin_pending_list_limit` pays for the cleanup. Set `WITH (fastupdate = off)` when steady response time matters more than insert speed ([GIN fast update](https://www.postgresql.org/docs/18/gin.html#GIN-FAST-UPDATE)).
- **GiST and SP-GiST for ranges, geometry and nearest-neighbour.** They serve overlap and containment operators and `ORDER BY location <-> point '(101,456)' LIMIT 10` ([index types](https://www.postgresql.org/docs/18/indexes-types.html)). GiST can be lossy: the plan shows `Rows Removed by Index Recheck` when the index returned false matches ([using EXPLAIN](https://www.postgresql.org/docs/18/using-explain.html)). Range constraints such as `WITHOUT OVERLAPS` belong to `pgsql-schema`.
- **BRIN for very large tables whose column follows the physical row order.** It stores a summary (by default min and max) per block range, so it is tiny and lossy: a bitmap scan reads whole ranges and rechecks rows ([BRIN](https://www.postgresql.org/docs/18/brin.html)). Use it for append-only, time-ordered data; check `pg_stats.correlation` first, since values near +1 or -1 mean the order matches ([pg_stats](https://www.postgresql.org/docs/18/view-pg-stats.html)).
- **Keep BRIN summaries current.** Pages added after the build stay unsummarized until a vacuum, `brin_summarize_new_values()`, or `WITH (autosummarize = on)` (off by default). A smaller `pages_per_range` (default 128) gives a larger but more precise index; the `minmax_multi` operator classes cope better with outlier values ([BRIN](https://www.postgresql.org/docs/18/brin.html), [CREATE INDEX](https://www.postgresql.org/docs/18/sql-createindex.html)).

## Text: prefix, infix and case-insensitive search

- **A default B-tree in a non-C database does not serve `LIKE 'abc%'`.** Anchored constant patterns (`col LIKE 'foo%'`, `col ~ '^foo'`) use a B-tree only in the C locale, or with the pattern operator classes `text_pattern_ops`, `varchar_pattern_ops` or `bpchar_pattern_ops` ([index types](https://www.postgresql.org/docs/18/indexes-types.html), [operator classes](https://www.postgresql.org/docs/18/indexes-opclass.html)). Check the database first: `SELECT datcollate, datlocprovider FROM pg_database WHERE datname = current_database();`

  ```sql
  CREATE INDEX customers_email_prefix_idx ON customers (email text_pattern_ops);
  ```

- **A pattern-ops index does not serve `<`, `<=`, `>`, `>=` or `ORDER BY`.** Equality still works. Keep a second, default index when range queries also need one ([operator classes](https://www.postgresql.org/docs/18/indexes-opclass.html)). An index declared `(email COLLATE "C")` also served prefix `LIKE` on 18.6 (checked 2026-10-27); it sorts in C order, so it serves range comparisons only when the query uses that collation ([collations](https://www.postgresql.org/docs/18/indexes-collations.html)).
- **The pattern must be known when the plan is made.** The B-tree prefix optimisation needs a constant pattern ([index types](https://www.postgresql.org/docs/18/indexes-types.html)), so a generic plan for `email LIKE $1 || '%'` or `email ^@ $1` fell back to a sequential scan on 18.6 while the custom plan used the index (checked 2026-10-27). When generic plans happen, and how to steer them, belongs to `pgsql-performance`. A trigram index avoids the problem, because its operators take the pattern at run time.
- **B-tree `ILIKE` works only for patterns that start with a non-letter.** For case-insensitive equality, index `lower(col)` and query `lower(col) = lower($1)` ([index types](https://www.postgresql.org/docs/18/indexes-types.html), [expression indexes](https://www.postgresql.org/docs/18/indexes-expressional.html)).
- **Use `pg_trgm` for infix, `ILIKE` and regular expressions.** `gin_trgm_ops` and `gist_trgm_ops` serve `LIKE`, `ILIKE`, `~`, `~*`, `=` and the similarity operators; they do not serve inequality operators, and a pattern with no extractable trigrams degrades to a full index scan ([pg_trgm](https://www.postgresql.org/docs/18/pgtrgm.html)). GiST handles `ORDER BY col <-> 'term' LIMIT n` efficiently, GIN does not. `pg_trgm` is a trusted extension, so a database owner with `CREATE` can install it.

  ```sql
  CREATE EXTENSION IF NOT EXISTS pg_trgm;
  CREATE INDEX customers_name_trgm_idx ON customers USING gin (name gin_trgm_ops);
  -- serves: WHERE name ILIKE '%' || $1 || '%'
  ```

- **Full-text search indexes `tsvector` with GIN.** GIN is the preferred type; GiST is lossy because each document becomes a fixed-length signature ([text search indexes](https://www.postgresql.org/docs/18/textsearch-indexes.html)). Index a stored `tsvector` column or the exact `to_tsvector('english', body)` expression the query uses, with the configuration named, since the one-argument form depends on a setting and is not IMMUTABLE.

## Collations

- **One collation per index column.** An index uses the column's collation and cannot serve a comparison written with another `COLLATE`; create a second index for that collation if both are queried ([collations](https://www.postgresql.org/docs/18/indexes-collations.html)).

## Listing operator classes

```sql
SELECT am.amname AS index_method, opc.opcname AS opclass_name,
       opc.opcintype::regtype AS indexed_type, opc.opcdefault AS is_default
FROM pg_am AS am
JOIN pg_opclass AS opc ON opc.opcmethod = am.oid
ORDER BY index_method, opclass_name;
```

## Newer in PostgreSQL 19 (hints)

- The default index operator classes for `inet` and `cidr` change from `btree_gist` to GiST's own, and `pg_upgrade` refuses clusters that still hold `btree_gist` `inet`/`cidr` indexes ([19 release notes](https://www.postgresql.org/docs/19/release-19.html)).
- `btree_gin` supports all cross-type comparisons that B-tree supports ([19 release notes](https://www.postgresql.org/docs/19/release-19.html)).

## Sources

- Index types: <https://www.postgresql.org/docs/18/indexes-types.html> (checked 2026-10-27)
- Operator classes and families: <https://www.postgresql.org/docs/18/indexes-opclass.html> (checked 2026-10-27)
- Indexes and collations: <https://www.postgresql.org/docs/18/indexes-collations.html> (checked 2026-10-27)
- Indexes and `ORDER BY`: <https://www.postgresql.org/docs/18/indexes-ordering.html> (checked 2026-10-27)
- Expression indexes: <https://www.postgresql.org/docs/18/indexes-expressional.html> (checked 2026-10-27)
- Hash indexes: <https://www.postgresql.org/docs/18/hash-index.html> (checked 2026-10-27)
- GIN: <https://www.postgresql.org/docs/18/gin.html> (checked 2026-10-27)
- BRIN: <https://www.postgresql.org/docs/18/brin.html> (checked 2026-10-27)
- `pg_stats`: <https://www.postgresql.org/docs/18/view-pg-stats.html> (checked 2026-10-27)
- `pg_trgm`: <https://www.postgresql.org/docs/18/pgtrgm.html> (checked 2026-10-27)
- Text search indexes: <https://www.postgresql.org/docs/18/textsearch-indexes.html> (checked 2026-10-27)
- Using `EXPLAIN`: <https://www.postgresql.org/docs/18/using-explain.html> (checked 2026-10-27)
- CREATE INDEX: <https://www.postgresql.org/docs/18/sql-createindex.html> (checked 2026-10-27)
- PostgreSQL 18 release notes: <https://www.postgresql.org/docs/18/release-18.html> (checked 2026-10-27)
- PostgreSQL 19 release notes, as of 2026-10-09: <https://www.postgresql.org/docs/19/release-19.html> (checked 2026-10-27)
