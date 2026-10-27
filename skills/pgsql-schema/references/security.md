# Roles, privileges and row-level security

Read when: a change adds roles or `GRANT` and `REVOKE`, creates a schema or relies on `search_path`, enables row-level security or writes `CREATE POLICY`, creates a view over protected tables, or adds a `SECURITY DEFINER` function.

Backstop: none for design. Squawk's `ban-create-policy`, `ban-alter-row-level-security` and `ban-revoke` rules only ban those statements in migrations ([squawk rules](https://squawkhq.com/docs/rules)).

## Rules

### Roles and grants

- **The application connects as a role that does not own the tables.** The right to alter or drop an object belongs to its owner and cannot be revoked ([privileges](https://www.postgresql.org/docs/18/ddl-priv.html)), and owners normally bypass row-level security ([row security](https://www.postgresql.org/docs/18/ddl-rowsecurity.html)). Run migrations as the owner and the service as a separate role with only the grants it needs.
- **Know what PUBLIC gets by default.** New functions and procedures grant EXECUTE to PUBLIC, types and domains grant USAGE, databases grant CONNECT and TEMPORARY; tables, sequences and schemas grant nothing ([privileges](https://www.postgresql.org/docs/18/ddl-priv.html)).
- **Grant future objects with `ALTER DEFAULT PRIVILEGES`**, so a table a later migration creates is readable by the service role without a new GRANT ([privileges](https://www.postgresql.org/docs/18/ddl-priv.html)).

```sql
CREATE ROLE app_service LOGIN;
GRANT USAGE ON SCHEMA app TO app_service;
GRANT SELECT, INSERT, UPDATE, DELETE ON ALL TABLES IN SCHEMA app TO app_service;
ALTER DEFAULT PRIVILEGES IN SCHEMA app
    GRANT SELECT, INSERT, UPDATE, DELETE ON TABLES TO app_service;
```

- **Use SCRAM passwords, not MD5.** PostgreSQL 18 deprecates MD5 password authentication and warns when one is set ([release notes](https://www.postgresql.org/docs/18/release-18.html)).

### Schemas and search_path

- **A database upgraded from PostgreSQL 14 or older still lets everyone create objects in `public`.** New databases on 15 and later do not. Run `REVOKE CREATE ON SCHEMA public FROM PUBLIC` on upgraded ones ([schemas](https://www.postgresql.org/docs/18/ddl-schemas.html)).
- **Putting a schema on `search_path` trusts everyone who can create objects in it.** Such a user can shadow a function or table and run code as the caller ([schemas](https://www.postgresql.org/docs/18/ddl-schemas.html)). Keep application objects in a schema only the owner can write.
- **Every `SECURITY DEFINER` function sets its own `search_path`, ending in `pg_temp`.** See `functions.md`.

### Row-level security

- **Enabling RLS with no policy denies everything** to roles subject to it ([row security](https://www.postgresql.org/docs/18/ddl-rowsecurity.html)).
- **Superusers and `BYPASSRLS` roles always bypass RLS, and the table owner does too** unless the table has `FORCE ROW LEVEL SECURITY` ([row security](https://www.postgresql.org/docs/18/ddl-rowsecurity.html)). Test policies as the application role, never as the owner.
- **`USING` filters the rows a command can see or target; `WITH CHECK` filters the rows it may write.** An `ALL` or `UPDATE` policy without `WITH CHECK` reuses `USING` for both ([CREATE POLICY](https://www.postgresql.org/docs/18/sql-createpolicy.html)).
- **Permissive policies combine with OR, restrictive ones with AND** ([row security](https://www.postgresql.org/docs/18/ddl-rowsecurity.html)). Add a tenant rule as `AS RESTRICTIVE` so a later permissive policy cannot widen it, and keep at least one permissive policy: with only restrictive ones, no rows are accessible ([CREATE POLICY](https://www.postgresql.org/docs/18/sql-createpolicy.html)).

```sql
ALTER TABLE invoice ENABLE ROW LEVEL SECURITY;
ALTER TABLE invoice FORCE ROW LEVEL SECURITY;

CREATE POLICY invoice_tenant ON invoice AS RESTRICTIVE
    USING (tenant_id = current_setting('app.tenant_id')::bigint)
    WITH CHECK (tenant_id = current_setting('app.tenant_id')::bigint);

CREATE POLICY invoice_access ON invoice
    USING (true);
```

- **Keep policy expressions on the row itself.** Policies that read only the current row are "the simplest and best-performing case"; policies that query other tables can race and leak ([row security](https://www.postgresql.org/docs/18/ddl-rowsecurity.html)). The policy runs for each row before the query's own conditions, except leakproof functions.
- **Unique and foreign key checks bypass RLS.** An insert that fails on a unique constraint tells the caller a hidden row exists; design keys with that covert channel in mind ([row security](https://www.postgresql.org/docs/18/ddl-rowsecurity.html)).

### Views

- **A view reads its tables with its owner's privileges and its owner's RLS policies**, by default ([CREATE VIEW](https://www.postgresql.org/docs/18/sql-createview.html)). A view owned by the table owner therefore shows every row to anyone allowed to select from it, unless the table forces RLS.
- **Create views over protected tables `WITH (security_invoker = true)`** so the caller's privileges and policies apply ([CREATE VIEW](https://www.postgresql.org/docs/18/sql-createview.html)).

```sql
CREATE VIEW invoice_open WITH (security_invoker = true) AS
    SELECT invoice_id, tenant_id, amount FROM invoice WHERE paid_at IS NULL;
```

- **A view that itself filters rows for security needs `security_barrier`**, so its conditions run before the caller's ([CREATE VIEW](https://www.postgresql.org/docs/18/sql-createview.html)).

## Sources

- Privileges: <https://www.postgresql.org/docs/18/ddl-priv.html> (checked 2026-10-27)
- Schemas, public schema and usage patterns: <https://www.postgresql.org/docs/18/ddl-schemas.html> (checked 2026-10-27)
- Row security policies: <https://www.postgresql.org/docs/18/ddl-rowsecurity.html>; CREATE POLICY: <https://www.postgresql.org/docs/18/sql-createpolicy.html> (checked 2026-10-27)
- CREATE VIEW, `security_invoker` and `security_barrier`: <https://www.postgresql.org/docs/18/sql-createview.html> (checked 2026-10-27)
- CREATE FUNCTION, writing SECURITY DEFINER functions safely: <https://www.postgresql.org/docs/18/sql-createfunction.html> (checked 2026-10-27)
- PostgreSQL 18 release notes, MD5 deprecation: <https://www.postgresql.org/docs/18/release-18.html> (checked 2026-10-27)
- Squawk rules: <https://squawkhq.com/docs/rules> (checked 2026-10-27)
