# Versions: what needs PostgreSQL 17, 18, or 19

Read when: a suggestion uses a recent feature and the project's server version is unknown or older than 18, or when deciding whether a PostgreSQL 19 feature may be used.

Backstop: `SHOW server_version;` on the project's database, or the image tag in its compose file or CI config.

## Rules

- **The floor is PostgreSQL 18.** The skills write PG 18 forms flat. When a project runs 17 or older, check this list before suggesting a feature, and say which suggestion needs an upgrade. Older features (15 and before) carry their version inline in the skill that teaches them.
- **PostgreSQL 19 is a hint, not a rule.** Release candidate 1 shipped on 2026-10-15 and there is no release date yet ([postgresql.org](https://www.postgresql.org/)). Use a 19 feature only when the project's server already runs 19, and label it.
- **Check incompatibilities on every major upgrade.** Each release notes page opens with a "Migration to Version N" section that lists behaviour changes. Read it before upgrading.

## Arrived in PostgreSQL 17

From the [PostgreSQL 17 release notes](https://www.postgresql.org/docs/17/release-17.html):

| Feature | Skill |
|---|---|
| `JSON_TABLE()`; SQL/JSON query functions `JSON_EXISTS()`, `JSON_QUERY()`, `JSON_VALUE()`; constructors `JSON()`, `JSON_SCALAR()`, `JSON_SERIALIZE()` | `pgsql-jsonb` |
| jsonpath methods `.bigint()`, `.boolean()`, `.date()`, `.decimal()`, `.integer()`, `.number()`, `.string()`, `.time()`, `.time_tz()`, `.timestamp()`, `.timestamp_tz()` | not covered |
| `MERGE ... RETURNING` with `merge_action()`; `WHEN NOT MATCHED BY SOURCE`; `MERGE` on updatable views | `pgsql-query` |
| `EXPLAIN (SERIALIZE)` and `EXPLAIN (MEMORY)` | `pgsql-performance` |
| `COPY ... ON_ERROR ignore` | not covered |
| B-tree indexes find a set of `IN` values more efficiently | `pgsql-indexing` |
| `ALTER TABLE ... ALTER COLUMN ... SET EXPRESSION` for generated columns; identity columns and exclusion constraints on partitioned tables | `pgsql-schema` |
| `transaction_timeout` setting | `pgsql-performance` |

## Arrived in PostgreSQL 18

From the [PostgreSQL 18 release notes](https://www.postgresql.org/docs/18/release-18.html):

| Feature | Skill |
|---|---|
| `uuidv7()` (and `uuidv4()` as an alias of `gen_random_uuid()`) | `pgsql-schema` |
| Generated columns may be `VIRTUAL`, and virtual is the default; `STORED` keeps the old behaviour | `pgsql-schema` |
| `OLD` and `NEW` in `RETURNING` for `INSERT`, `UPDATE`, `DELETE`, `MERGE` | `pgsql-query` |
| `PRIMARY KEY` and `UNIQUE ... WITHOUT OVERLAPS`; foreign keys with `PERIOD` | `pgsql-schema` |
| `CHECK` and foreign key constraints may be `NOT ENFORCED` | `pgsql-schema` |
| `ALTER TABLE` can set `NOT VALID` on `NOT NULL` constraints | `pgsql-migrations` |
| B-tree skip scan; `OR` clauses transformed to arrays for index processing | `pgsql-indexing` |
| `EXPLAIN ANALYZE` includes `BUFFERS` automatically; index scans report lookup counts | `pgsql-performance` |
| Asynchronous I/O (`io_method`) | not covered |
| `casefold()` for case-insensitive matching; `PG_UNICODE_FAST` collation | not covered |
| jsonb `null` casts to a scalar type as SQL `NULL` instead of raising an error; `json[b]_strip_nulls` can remove null array elements | `pgsql-jsonb` |
| `pg_upgrade` keeps planner statistics | not covered |
| MD5 password authentication deprecated; use SCRAM | `pgsql-schema` |

"Not covered" marks a feature no skill teaches yet; cite the release notes if it comes up.

PG 18 incompatibilities that reach application SQL include: `VACUUM` and `ANALYZE` now process inheritance children by default (`ONLY` restores the old behaviour), `COPY FROM` no longer treats `\.` as an end-of-file marker in CSV files (psql still does when it reads from `STDIN`), and `AFTER` triggers run as the role that was active when the event was queued ([release notes, migration section](https://www.postgresql.org/docs/18/release-18.html)).

## PostgreSQL 19 (release candidate; hints only)

From the [PostgreSQL 19 release notes](https://www.postgresql.org/docs/19/release-19.html), as of 2026-10-09. The notes may still change before release.

| Feature | Skill |
|---|---|
| `INSERT ... ON CONFLICT DO SELECT ... RETURNING` | `pgsql-query` |
| `IGNORE NULLS` and `RESPECT NULLS` for `lead()`, `lag()`, `first_value()`, `last_value()`, `nth_value()` | `pgsql-query` |
| jsonpath string methods (`lower()`, `upper()`, `replace()`, `split_part()`, trims); `IS JSON` on domains; `COPY ... TO` in JSON | `pgsql-jsonb` |
| `REPACK` and `REPACK (CONCURRENTLY)` replace `VACUUM FULL` and `CLUSTER` | `pgsql-migrations` |
| `ALTER CONSTRAINT ... [NOT] ENFORCED` on `CHECK` constraints | `pgsql-schema` |
| Planner: `NOT IN` becomes an anti-join when NULLs cannot occur; aggregation before joins; `EXPLAIN (ANALYZE, IO)`; JIT off by default | `pgsql-performance` |
| `pg_plan_advice` and `pg_stash_advice` extensions | `pgsql-performance` |

PG 19 incompatibilities to watch: `json_array()` over zero rows returns `[]` instead of `NULL`; `standard_conforming_strings` is always on; `default_toast_compression` becomes `lz4`; RADIUS authentication is removed.

## Sources

- PostgreSQL 17 release notes: <https://www.postgresql.org/docs/17/release-17.html> (checked 2026-10-27)
- PostgreSQL 18 release notes: <https://www.postgresql.org/docs/18/release-18.html> (checked 2026-10-27; latest minor 18.6, 2026-08-13)
- PostgreSQL 19 release notes: <https://www.postgresql.org/docs/19/release-19.html> (checked 2026-10-27; notes as of 2026-10-09)
- PostgreSQL 19 RC 1 announcement on the home page: <https://www.postgresql.org/> (checked 2026-10-27)
