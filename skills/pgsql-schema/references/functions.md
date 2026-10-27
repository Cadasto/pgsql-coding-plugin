# Functions, procedures and triggers

Read when: a change adds or edits `CREATE FUNCTION`, `CREATE PROCEDURE`, a PL/pgSQL body, `EXECUTE` with dynamic SQL, a volatility, `STRICT` or `PARALLEL` label, `SECURITY DEFINER`, or `CREATE TRIGGER`.

Backstop: install the plpgsql_check extension in a development database and run it on every PL/pgSQL function. It finds missing objects, type mismatches, unused variables and dead code; `security_warnings => true` adds SQL injection checks and `performance_warnings => true` adds hidden-cast warnings ([plpgsql_check](https://github.com/okbob/plpgsql_check)). Trigger functions need the table as second argument.

```sql
SELECT * FROM plpgsql_check_function('order_total(bigint)', security_warnings => true);
SELECT * FROM plpgsql_check_function('order_audit_trg()', 'order_line');
```

## Contents

- SQL or PL/pgSQL
- Volatility, STRICT, PARALLEL
- SECURITY DEFINER
- Dynamic SQL in PL/pgSQL
- Triggers

## Rules

### SQL or PL/pgSQL

- **Write a `LANGUAGE sql` function with a standard body (`RETURN` or `BEGIN ATOMIC`), not a quoted string.** The standard body is parsed when the function is created and records its dependencies, so `DROP ... CASCADE` works; a string body is parsed at run time and can leave a dangling function ([CREATE FUNCTION](https://www.postgresql.org/docs/18/sql-createfunction.html)). It cannot take polymorphic arguments.

```sql
CREATE FUNCTION order_total(p_order_id bigint) RETURNS numeric
    LANGUAGE sql STABLE PARALLEL SAFE
BEGIN ATOMIC
    SELECT coalesce(sum(quantity * unit_price), 0)
    FROM order_line
    WHERE order_id = p_order_id;
END;
```

- **Use PL/pgSQL when the body needs control flow, variables or dynamic SQL**, and run plpgsql_check on it, since its embedded SQL is not validated at creation time ([plpgsql_check](https://github.com/okbob/plpgsql_check)).
- **`SELECT ... INTO STRICT` when exactly one row must come back.** Without `STRICT`, no rows leaves nulls and extra rows are silently dropped; with it, PL/pgSQL raises `NO_DATA_FOUND` or `TOO_MANY_ROWS` ([PL/pgSQL statements](https://www.postgresql.org/docs/18/plpgsql-statements.html)).

### Volatility, STRICT, PARALLEL

- **Label each function with the strictest true volatility.** `VOLATILE` is the default and is re-evaluated for every row. `STABLE` returns the same result within one statement and may be used in an index scan condition. `IMMUTABLE` returns the same result forever and can be folded to a constant at plan time ([volatility](https://www.postgresql.org/docs/18/xfunc-volatility.html)).
- **Anything that reads a setting is not IMMUTABLE.** A function whose result depends on `TimeZone` is STABLE; a false IMMUTABLE label can freeze a stale value into a prepared statement or a cached PL/pgSQL plan ([volatility](https://www.postgresql.org/docs/18/xfunc-volatility.html)).
- **Never relabel a STABLE function IMMUTABLE to get an index**; the index rule is `pgsql-indexing`'s.
- **STABLE and IMMUTABLE functions see the snapshot of the calling query** and may only run `SELECT`; a `VOLATILE` function sees changes made by the calling statement ([volatility](https://www.postgresql.org/docs/18/xfunc-volatility.html)).
- **`STRICT` skips the call on any null argument** and returns null ([CREATE FUNCTION](https://www.postgresql.org/docs/18/sql-createfunction.html)). Use it when null in means null out.
- **`PARALLEL UNSAFE` is the default and forces a serial plan for the whole statement.** Mark a read-only function `PARALLEL SAFE` so a query that calls it can still use parallel workers; "if in doubt", leave it UNSAFE ([CREATE FUNCTION](https://www.postgresql.org/docs/18/sql-createfunction.html)).

### SECURITY DEFINER

- **Set `search_path` on the function, ending with `pg_temp`.** The temporary schema is searched first by default and is writable by anyone, so a caller could shadow a table the function uses ([CREATE FUNCTION](https://www.postgresql.org/docs/18/sql-createfunction.html)).
- **Revoke EXECUTE from PUBLIC in the same transaction as the CREATE.** New functions are executable by PUBLIC by default ([CREATE FUNCTION](https://www.postgresql.org/docs/18/sql-createfunction.html), [privileges](https://www.postgresql.org/docs/18/ddl-priv.html)).

```sql
BEGIN;
CREATE FUNCTION app.close_account(p_account_id bigint) RETURNS void
    LANGUAGE plpgsql SECURITY DEFINER
    SET search_path = app, pg_temp
AS $$
BEGIN
    UPDATE account SET closed_at = now() WHERE account_id = p_account_id;
END;
$$;
REVOKE ALL ON FUNCTION app.close_account(bigint) FROM PUBLIC;
GRANT EXECUTE ON FUNCTION app.close_account(bigint) TO app_support;
COMMIT;
```

### Dynamic SQL in PL/pgSQL

- **Values go through `USING`, identifiers through `format('%I', ...)`.** Parameters `$1`, `$2` bind data values only; a table or column name must be inserted as text, quoted by `%I` (`quote_ident`). `USING` keeps values in their own type and avoids injection ([PL/pgSQL statements](https://www.postgresql.org/docs/18/plpgsql-statements.html)).

```sql
EXECUTE format('UPDATE %I SET %I = $1 WHERE id = $2', p_table, p_column)
    USING p_value, p_id;
```

- **Never concatenate input into the command with `||`.** No PL/pgSQL variable is substituted inside an `EXECUTE` string, and dollar quoting protects only fixed text; text not known in advance must pass through `quote_ident`, `quote_literal` or `quote_nullable` ([PL/pgSQL statements](https://www.postgresql.org/docs/18/plpgsql-statements.html)). `format('%I')` is `quote_ident` and `format('%L')` is `quote_nullable`.
- **`%L` only where a parameter cannot go.** `$n` parameters work only in `SELECT`, `INSERT`, `UPDATE`, `DELETE` and `MERGE`; in utility statements such as `CREATE` or `ALTER`, data values must be quoted into the text. Prefer `quote_nullable` (`%L`) to `quote_literal`, which returns null for a null argument ([PL/pgSQL statements](https://www.postgresql.org/docs/18/plpgsql-statements.html)).

```sql
EXECUTE format('ALTER ROLE %I SET statement_timeout = %L', p_role, p_timeout);
```

- **Read results with `EXECUTE ... INTO [STRICT]`.** `SELECT INTO` is not supported inside an `EXECUTE` string ([PL/pgSQL statements](https://www.postgresql.org/docs/18/plpgsql-statements.html)).
- **`EXECUTE` plans every time.** It never caches a plan, which helps when the best plan depends on the values ([PL/pgSQL statements](https://www.postgresql.org/docs/18/plpgsql-statements.html)).

### Triggers

- **Say `FOR EACH ROW` when the trigger is per row.** `FOR EACH STATEMENT` is the default when neither is written, and a statement trigger fires even when no row changes ([CREATE TRIGGER](https://www.postgresql.org/docs/18/sql-createtrigger.html)).
- **Change the row in a BEFORE row trigger; react to it in an AFTER trigger.** BEFORE can modify or skip the row; AFTER sees all changes, including other triggers' ([CREATE TRIGGER](https://www.postgresql.org/docs/18/sql-createtrigger.html)). Generated columns cannot be read in BEFORE triggers ([generated columns](https://www.postgresql.org/docs/18/ddl-generated-columns.html)).
- **Filter with `WHEN`.** In an AFTER trigger a false `WHEN` means no event is queued, which speeds up statements that touch many rows ([CREATE TRIGGER](https://www.postgresql.org/docs/18/sql-createtrigger.html)).

```sql
CREATE TRIGGER account_balance_audit
    AFTER UPDATE ON account
    FOR EACH ROW
    WHEN (OLD.balance IS DISTINCT FROM NEW.balance)
    EXECUTE FUNCTION account_balance_audit();
```

- **Bulk work belongs in a statement trigger with transition tables.** `REFERENCING NEW TABLE AS ... OLD TABLE AS ...` gives an AFTER trigger every row the statement changed, in one call ([CREATE TRIGGER](https://www.postgresql.org/docs/18/sql-createtrigger.html)).
- **AFTER triggers run as the role that queued them.** Since PostgreSQL 18, not the role active at commit ([release notes](https://www.postgresql.org/docs/18/release-18.html)).
- **Triggers, never rules.** Rules rewrite queries and "all non-trivial rules are incorrect" ([Don't Do This](https://wiki.postgresql.org/wiki/Don%27t_Do_This)).

## Sources

- CREATE FUNCTION (SQL bodies, STRICT, PARALLEL, LEAKPROOF, SECURITY DEFINER): <https://www.postgresql.org/docs/18/sql-createfunction.html> (checked 2026-10-27)
- Function volatility categories: <https://www.postgresql.org/docs/18/xfunc-volatility.html> (checked 2026-10-27)
- PL/pgSQL basic statements, dynamic commands: <https://www.postgresql.org/docs/18/plpgsql-statements.html> (checked 2026-10-27)
- CREATE TRIGGER: <https://www.postgresql.org/docs/18/sql-createtrigger.html> (checked 2026-10-27)
- Privileges, PUBLIC defaults: <https://www.postgresql.org/docs/18/ddl-priv.html> (checked 2026-10-27)
- Generated columns: <https://www.postgresql.org/docs/18/ddl-generated-columns.html> (checked 2026-10-27)
- PostgreSQL 18 release notes: <https://www.postgresql.org/docs/18/release-18.html> (checked 2026-10-27)
- plpgsql_check README, PostgreSQL 14 to 20, at GitHub release tag v2.10.16 (the PGXN distribution lags at 2.10.4): <https://github.com/okbob/plpgsql_check> (checked 2026-10-27)
- PostgreSQL wiki, Don't Do This: <https://wiki.postgresql.org/wiki/Don%27t_Do_This> (checked 2026-10-27)
