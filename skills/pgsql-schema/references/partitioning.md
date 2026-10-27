# Partitioning

Read when: a design reaches for `PARTITION BY`, a time-series or log table that will grow past memory, retention by dropping old data, a default partition, partition pruning, or detaching a partition.

Backstop: `EXPLAIN` on the queries that matter shows whether pruning removed partitions (`pgsql-performance`). Squawk's `require-concurrent-partition-detach` flags a blocking detach in a migration ([squawk rules](https://squawkhq.com/docs/rules)).

## Rules

### When to partition

- **Partition only a table that would otherwise be very large.** The manual's rule of thumb is a table bigger than the server's physical memory ([partitioning](https://www.postgresql.org/docs/18/ddl-partitioning.html)).
- **Partition when retention or bulk loads follow the key.** Dropping or detaching a partition is far faster than a bulk `DELETE` and avoids its `VACUUM` cost ([partitioning](https://www.postgresql.org/docs/18/ddl-partitioning.html)).
- **Key on the column most queries filter by.** Pruning needs the key in the `WHERE` clause, and can also prune at execution time from parameters and subquery results ([partitioning](https://www.postgresql.org/docs/18/ddl-partitioning.html)).
- **Do not over-partition.** Planning handles "up to a few thousand partitions fairly well" when queries prune most of them; too many costs planning time and memory, too few leaves indexes large ([partitioning](https://www.postgresql.org/docs/18/ddl-partitioning.html)).
- **Native partitioning, never table inheritance**, for new designs ([Don't Do This](https://wiki.postgresql.org/wiki/Don%27t_Do_This)).

### Shape

- **Range for time, list for a small set of values, hash to spread rows evenly.** Range bounds include the lower end and exclude the upper end, so adjacent partitions share a bound ([partitioning](https://www.postgresql.org/docs/18/ddl-partitioning.html)).

```sql
CREATE TABLE event_log (
    event_id    bigint GENERATED ALWAYS AS IDENTITY,
    occurred_at timestamptz NOT NULL,
    payload     jsonb NOT NULL,
    CONSTRAINT event_log_pkey PRIMARY KEY (event_id, occurred_at)
) PARTITION BY RANGE (occurred_at);

CREATE TABLE event_log_2026_11 PARTITION OF event_log
    FOR VALUES FROM ('2026-11-01') TO ('2026-12-01');
```

- **Every PRIMARY KEY and UNIQUE constraint includes all partition key columns**, and a table that needs one cannot partition on an expression. Each partition's index can only enforce uniqueness inside that partition ([partitioning](https://www.postgresql.org/docs/18/ddl-partitioning.html)). An exclusion constraint must compare the key columns with `=` ([CREATE TABLE](https://www.postgresql.org/docs/18/sql-createtable.html)).
- **A generated column cannot be part of the partition key** ([generated columns](https://www.postgresql.org/docs/18/ddl-generated-columns.html)).
- **Partitions have exactly the parent's columns** ([partitioning](https://www.postgresql.org/docs/18/ddl-partitioning.html)).
- **Partitioned tables cannot be unlogged** in PostgreSQL 18 ([release notes](https://www.postgresql.org/docs/18/release-18.html)).

### Default partition and partition lifecycle

- **Without a default partition, a row that fits no partition is an error.** Create future partitions ahead of time, from a scheduled job or a migration ([partitioning](https://www.postgresql.org/docs/18/ddl-partitioning.html)).
- **A default partition makes later changes slower.** Attaching a partition scans the default partition under an `ACCESS EXCLUSIVE` lock unless a CHECK constraint rules the new range out, and `DETACH PARTITION ... CONCURRENTLY` is not allowed while a default partition exists ([ALTER TABLE](https://www.postgresql.org/docs/18/sql-altertable.html), [partitioning](https://www.postgresql.org/docs/18/ddl-partitioning.html)). Prefer no default partition on tables whose old partitions are detached.
- **Detach with `CONCURRENTLY` on a live table.** Its lock, transaction limits and `FINALIZE` are in `pgsql-migrations`.
- **Adding an index to a live partitioned table** follows the recipe in `pgsql-migrations`; which index to build is `pgsql-indexing`.

### Statistics

- **Autovacuum does not analyze the partitioned parent, only its partitions.** Run `ANALYZE` on the parent after large loads when queries depend on parent-level statistics; PostgreSQL 18 adds `ANALYZE ONLY` to skip the children ([release notes](https://www.postgresql.org/docs/18/release-18.html)).

## Sources

- Table partitioning: <https://www.postgresql.org/docs/18/ddl-partitioning.html> (checked 2026-10-27)
- ALTER TABLE, ATTACH and DETACH PARTITION: <https://www.postgresql.org/docs/18/sql-altertable.html> (checked 2026-10-27)
- CREATE TABLE, constraints on partitioned tables: <https://www.postgresql.org/docs/18/sql-createtable.html> (checked 2026-10-27)
- Generated columns: <https://www.postgresql.org/docs/18/ddl-generated-columns.html> (checked 2026-10-27)
- PostgreSQL 18 release notes: <https://www.postgresql.org/docs/18/release-18.html> (checked 2026-10-27)
- PostgreSQL wiki, Don't Do This: <https://wiki.postgresql.org/wiki/Don%27t_Do_This> (checked 2026-10-27)
- Squawk rules: <https://squawkhq.com/docs/rules> (checked 2026-10-27)
