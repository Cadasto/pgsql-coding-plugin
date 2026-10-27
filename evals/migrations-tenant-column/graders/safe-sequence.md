---
type: llm
weight: 2
---

PASS if all of these hold:
- The answer says the teammate's migration is unsafe and names at least two concrete reasons, such as: goose runs the whole file in one transaction, so the `ACCESS EXCLUSIVE` lock from `ADD COLUMN` is held through the full-table `UPDATE`; `SET NOT NULL` scans the table under `ACCESS EXCLUSIVE`; the foreign key validates every row while blocking writes; the plain `CREATE INDEX` blocks writes for the whole build.
- Every rewritten migration file whose DDL takes `ACCESS EXCLUSIVE` or `SHARE ROW EXCLUSIVE` (adding the column, adding the foreign key or not-null constraint) sets `lock_timeout` before its first DDL statement. A file holding only concurrent index statements is not required to set it; setting `lock_timeout = 0` there, or saying that a short `lock_timeout` would abort the concurrent build, is correct.
- The foreign key is added with `NOT VALID`, and `VALIDATE CONSTRAINT` runs in a later, separate migration file.
- The index is built with `CREATE INDEX CONCURRENTLY` in a goose file marked `-- +goose NO TRANSACTION` (any letter case).
- The backfill runs in batches with a commit per batch (for example by primary-key ranges from a script or job), not as one `UPDATE` over the whole table in a single transaction.
- New and updated orders get `tenant_id` before any not-null or `CHECK` constraint on it exists: the application (or a trigger or default) sets it, and the backfill finishes first.
- `NOT NULL` is reached without a full scan under `ACCESS EXCLUSIVE`, after the backfill: either `ADD CONSTRAINT ... NOT NULL tenant_id NOT VALID` followed by `VALIDATE CONSTRAINT` in a later migration, or `CHECK (tenant_id IS NOT NULL) NOT VALID`, `VALIDATE CONSTRAINT`, then `SET NOT NULL`.

FAIL if any of these holds: a `CREATE INDEX` on `orders` without `CONCURRENTLY`; `CREATE INDEX CONCURRENTLY` in a goose file without the no-transaction annotation; the foreign key added without `NOT VALID`, or `NOT VALID` and `VALIDATE CONSTRAINT` in the same migration file; the backfill kept as one `UPDATE` over all rows in one transaction; a `NOT NULL ... NOT VALID` or `CHECK (tenant_id IS NOT NULL) NOT VALID` constraint added before the backfill has finished, since it rejects updates of rows still NULL; `SET NOT NULL` on `tenant_id` with no validated not-null or `CHECK` constraint before it; no `lock_timeout` anywhere in the rewrite.
