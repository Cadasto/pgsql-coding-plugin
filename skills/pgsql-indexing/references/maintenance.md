# Index maintenance and evidence

Read when: a task asks which indexes are unused, duplicated, redundant or invalid, looks for foreign keys without an index, suspects index bloat or a stuck GIN pending list, follows an OS, glibc or ICU upgrade, or wants to test an index before creating it.

Backstop: the catalog queries below; each runs read-only on PostgreSQL 18 (run on 18.6, 2026-10-27). Building and rebuilding indexes on a live table, including `CONCURRENTLY` and partitioned tables, belongs to `pgsql-migrations`.

## Contents

- Invalid indexes
- Unused indexes
- Duplicate and redundant indexes
- Foreign keys without an index
- Bloat and the GIN pending list
- Collation changes
- What-if testing with HypoPG, then PostgreSQL 19 hints

## Invalid indexes

`indisvalid = false` means the index "cannot safely be used for queries", and a unique one does not guarantee uniqueness ([pg_index](https://www.postgresql.org/docs/18/catalog-pg-index.html)). A failed `CREATE INDEX CONCURRENTLY` or `REINDEX CONCURRENTLY` leaves one behind that every write still maintains ([CREATE INDEX](https://www.postgresql.org/docs/18/sql-createindex.html#SQL-CREATEINDEX-CONCURRENTLY)); the rebuild recipe belongs to `pgsql-migrations`.

```sql
SELECT indexrelid::regclass AS index_name, indrelid::regclass AS table_name
FROM pg_index
WHERE NOT indisvalid;
```

## Unused indexes

```sql
SELECT s.relname AS table_name, s.indexrelname AS index_name,
       pg_size_pretty(pg_relation_size(s.indexrelid)) AS index_size,
       s.idx_scan, s.last_idx_scan
FROM pg_stat_user_indexes AS s
JOIN pg_index AS i ON i.indexrelid = s.indexrelid
WHERE s.idx_scan = 0
  AND NOT i.indisunique
  AND NOT EXISTS (SELECT 1 FROM pg_constraint AS c WHERE c.conindid = s.indexrelid)
ORDER BY pg_relation_size(s.indexrelid) DESC;
```

- **Counters cover only the time since the last reset.** Check `SELECT stats_reset FROM pg_stat_database WHERE datname = current_database();` before trusting a zero. A crash, an immediate shutdown or a restore from backup resets all counters ([cumulative statistics](https://www.postgresql.org/docs/18/monitoring-stats.html)).
- **Each standby counts its own scans.** Index usage on a standby is recorded on that standby, not on the primary ([hot standby](https://www.postgresql.org/docs/18/hot-standby.html)); check every replica that serves reads before dropping.
- **Keep indexes that enforce constraints.** Unique, primary-key and exclusion indexes do work at write time even with `idx_scan = 0`; the query above excludes them.

## Duplicate and redundant indexes

Exact duplicates share table, columns, operator classes, collations, sort options, expression and predicate:

```sql
SELECT indrelid::regclass AS table_name, array_agg(indexrelid::regclass) AS indexes
FROM pg_index
GROUP BY indrelid, indkey::text, indclass::text, indcollation::text, indoption::text,
         coalesce(pg_get_expr(indexprs, indrelid), ''), coalesce(pg_get_expr(indpred, indrelid), '')
HAVING count(*) > 1;
```

A non-unique B-tree whose key columns lead a longer one is usually redundant, because the longer index serves conditions on its leading columns ([multicolumn indexes](https://www.postgresql.org/docs/18/indexes-multicolumn.html)). This query skips expression, partial and `INCLUDE` indexes; check sort direction before dropping:

```sql
SELECT a.indexrelid::regclass AS redundant_index, b.indexrelid::regclass AS covered_by
FROM pg_index AS a
JOIN pg_index AS b ON b.indrelid = a.indrelid AND b.indexrelid <> a.indexrelid
JOIN pg_class AS ca ON ca.oid = a.indexrelid
JOIN pg_class AS cb ON cb.oid = b.indexrelid
WHERE ca.relam = cb.relam
  AND NOT a.indisunique
  AND a.indexprs IS NULL AND b.indexprs IS NULL
  AND a.indpred IS NULL AND b.indpred IS NULL
  AND a.indnatts = a.indnkeyatts AND b.indnatts = b.indnkeyatts
  AND a.indnkeyatts < b.indnkeyatts
  AND b.indkey::text || ' ' LIKE a.indkey::text || ' %'
  AND b.indclass::text || ' ' LIKE a.indclass::text || ' %';
```

## Foreign keys without an index

Lists foreign keys whose columns do not lead any non-partial index on the referencing table ([constraints](https://www.postgresql.org/docs/18/ddl-constraints.html)):

```sql
SELECT c.conrelid::regclass AS table_name, c.conname AS fk_name, pg_get_constraintdef(c.oid) AS definition
FROM pg_constraint AS c
WHERE c.contype = 'f'
  AND NOT EXISTS (
    SELECT 1 FROM pg_index AS i
    WHERE i.indrelid = c.conrelid AND i.indpred IS NULL
      AND (string_to_array(i.indkey::text, ' ')::int2[])[1:cardinality(c.conkey)] @> c.conkey
      AND (string_to_array(i.indkey::text, ' ')::int2[])[1:cardinality(c.conkey)] <@ c.conkey);
```

## Bloat and the GIN pending list

- **Measure before rebuilding.** `pgstattuple`'s `pgstatindex('index_name')` reports `avg_leaf_density` and `leaf_fragmentation` for a B-tree; it needs superuser or the `pg_stat_scan_tables` role ([pgstattuple](https://www.postgresql.org/docs/18/pgstattuple.html)). A bloated index needs a rebuild ([REINDEX](https://www.postgresql.org/docs/18/sql-reindex.html)), done as `pgsql-migrations` describes.
- **A long GIN pending list slows every search.** `pgstatginindex('index_name')` shows `pending_pages` and `pending_tuples` ([pgstattuple](https://www.postgresql.org/docs/18/pgstattuple.html)); vacuum, `gin_clean_pending_list()`, or `fastupdate = off` clears or avoids it ([GIN fast update](https://www.postgresql.org/docs/18/gin.html#GIN-FAST-UPDATE)).

## Collation changes

- **Reindex text indexes after the collation library changes.** An OS major upgrade (glibc) or a newer ICU can change sort order and "lead to corrupt indexes"; PostgreSQL warns "collation ... has version mismatch". Rebuild the affected objects with `REINDEX`, then run `ALTER COLLATION ... REFRESH VERSION` or `ALTER DATABASE ... REFRESH COLLATION VERSION`; that page gives a `pg_depend` query listing affected objects ([ALTER COLLATION](https://www.postgresql.org/docs/18/sql-altercollation.html)). After `pg_upgrade` to 18 on an ICU or builtin default provider, also reindex full-text and `pg_trgm` indexes ([18 release notes](https://www.postgresql.org/docs/18/release-18.html)).

## What-if testing with HypoPG

The HypoPG extension creates hypothetical indexes in the session's private memory, so a candidate costs nothing to try ([HypoPG usage](https://hypopg.readthedocs.io/en/latest/usage.html)). Only plain `EXPLAIN` sees them, never `EXPLAIN ANALYZE`; confirm a winner with a real build on a copy.

```sql
SELECT * FROM hypopg_create_index('CREATE INDEX ON orders (customer_id, created_at)');
EXPLAIN SELECT id FROM orders WHERE customer_id = 42 ORDER BY created_at DESC LIMIT 20;
SELECT index_name, pg_size_pretty(hypopg_relation_size(indexrelid)) FROM hypopg_list_indexes;
SELECT hypopg_reset();  -- hypopg_hide_index(oid) instead previews a plan without a real index
```

## Newer in PostgreSQL 19 (hints)

- `pg_stat_all_indexes` and `pg_stat_user_indexes` gain a `stats_reset` column, so an unused-index check can read the reset time per index ([19 release notes](https://www.postgresql.org/docs/19/release-19.html)).
- `REPACK` rewrites a table and all its indexes; `REPACK (CONCURRENTLY) ... USING INDEX` reorders rows by an index without blocking reads and writes, which can restore the physical order a BRIN index depends on ([REPACK](https://www.postgresql.org/docs/19/sql-repack.html)).
- Autovacuum can vacuum a table's indexes with parallel workers ([19 release notes](https://www.postgresql.org/docs/19/release-19.html)).

## Sources

- CREATE INDEX (invalid leftovers): <https://www.postgresql.org/docs/18/sql-createindex.html> (checked 2026-10-27)
- REINDEX: <https://www.postgresql.org/docs/18/sql-reindex.html> (checked 2026-10-27)
- `pg_index`: <https://www.postgresql.org/docs/18/catalog-pg-index.html> (checked 2026-10-27)
- Cumulative statistics (`pg_stat_user_indexes`, resets): <https://www.postgresql.org/docs/18/monitoring-stats.html> (checked 2026-10-27)
- Hot standby (statistics on a standby): <https://www.postgresql.org/docs/18/hot-standby.html> (checked 2026-10-27)
- Multicolumn indexes: <https://www.postgresql.org/docs/18/indexes-multicolumn.html> (checked 2026-10-27)
- Constraints (foreign keys): <https://www.postgresql.org/docs/18/ddl-constraints.html> (checked 2026-10-27)
- pgstattuple: <https://www.postgresql.org/docs/18/pgstattuple.html> (checked 2026-10-27)
- GIN: <https://www.postgresql.org/docs/18/gin.html> (checked 2026-10-27)
- ALTER COLLATION: <https://www.postgresql.org/docs/18/sql-altercollation.html> (checked 2026-10-27)
- PostgreSQL 18 release notes: <https://www.postgresql.org/docs/18/release-18.html> (checked 2026-10-27)
- HypoPG usage: <https://hypopg.readthedocs.io/en/latest/usage.html> (checked 2026-10-27)
- PostgreSQL wiki, Index Maintenance (query shapes): <https://wiki.postgresql.org/wiki/Index_Maintenance> (checked 2026-10-27)
- PostgreSQL 19 release notes, as of 2026-10-09: <https://www.postgresql.org/docs/19/release-19.html> (checked 2026-10-27)
- REPACK (19): <https://www.postgresql.org/docs/19/sql-repack.html> (checked 2026-10-27)
