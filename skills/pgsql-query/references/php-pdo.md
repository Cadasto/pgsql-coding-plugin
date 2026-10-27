# PHP with PDO pgsql

Read when: a `.php` file creates a `PDO` or `Pdo\Pgsql` connection to PostgreSQL, calls `prepare`, `execute`, `bindValue`, `beginTransaction`, `copyFromArray` or `escapeIdentifier`, reads a `bytea` column, binds a boolean, or catches a `PDOException`.

Deterministic backstop: php-cs-fixer and PHPStan, owned by php-coding. They do not see SQL. Bound parameters and allowlisted identifiers are in the php-coding security reference; this file covers only what PostgreSQL adds. jsonb operators and the `??` escape belong to `pgsql-jsonb`.

## Rules

- **Keep the exception error mode.** `PDO::ERRMODE_EXCEPTION` is the default since PHP 8.0 and throws `PDOException` ([errors and error handling](https://www.php.net/manual/en/pdo.error-handling.php)). Do not set `ERRMODE_SILENT`.
- **Use native prepared statements.** With `ATTR_EMULATE_PREPARES` set to true, PDO always emulates instead of sending parameters to the server ([PDO::setAttribute](https://www.php.net/manual/en/pdo.setattribute.php)). For a statement run once, `Pdo\Pgsql::ATTR_DISABLE_PREPARES` sends query and parameters in one call and saves a round trip ([Pdo\Pgsql](https://www.php.net/manual/en/class.pdo-pgsql.php)).
- **Use one placeholder style per statement, and a name only once.** Named and `?` markers cannot be mixed. A named marker cannot repeat unless emulation is on, so give a repeated value two names ([PDO::prepare](https://www.php.net/manual/en/pdo.prepare.php)).
- **Bind a list as one PostgreSQL array literal** and compare with `= ANY(CAST(? AS bigint[]))`. Build the literal only from validated integers, because elements with commas, braces, quotes or whitespace need array quoting ([arrays](https://www.postgresql.org/docs/18/arrays.html#ARRAYS-IO)).
- **Bind booleans and NULL with an explicit type.** `execute($params)` treats every value as `PDO::PARAM_STR` ([PDOStatement::execute](https://www.php.net/manual/en/pdostatement.execute.php)). PHP `false` becomes an empty string, which is not a valid PostgreSQL boolean ([boolean type](https://www.postgresql.org/docs/18/datatype-boolean.html)). Use `bindValue(':flag', $flag, PDO::PARAM_BOOL)` and `PDO::PARAM_NULL`.
- **Expect `bytea` back as a stream.** pdo_pgsql returns `bytea` columns as stream resources; read them with `stream_get_contents()`. Bind binary input with `PDO::PARAM_LOB` ([PDO_PGSQL](https://www.php.net/manual/en/ref.pdo-pgsql.php), [large objects](https://www.php.net/manual/en/pdo.lobs.php)).
- **Branch on `PDOException::getCode()` as a string SQLSTATE.** It holds the SQLSTATE, such as `'23505'` or `'40001'`. Do not cast it to `int`, because codes like `'40P01'` contain letters. `errorInfo` adds the driver code and message ([PDOException](https://www.php.net/manual/en/class.pdoexception.php)). Retry rules are in `transactions.md`.
- **On PHP 8.4, use the `Pdo\Pgsql` class constants and methods.** The `PDO::PGSQL_*` constants and `PDO::pgsql*` methods are aliases, and `PDO::PGSQL_ATTR_DISABLE_PREPARES` is deprecated in PHP 8.5 ([PDO_PGSQL](https://www.php.net/manual/en/ref.pdo-pgsql.php)).
- **Quote a dynamic identifier with `Pdo\Pgsql::escapeIdentifier()`** when an allowlist maps input to a name that still needs quoting. Never pass it raw input ([Pdo\Pgsql](https://www.php.net/manual/en/class.pdo-pgsql.php)).
- **Bulk-load with `Pdo\Pgsql::copyFromArray()`.** It copies rows from a PHP array into a table in one call. Set `$separator` and `$nullAs` to match the row strings ([Pdo\Pgsql](https://www.php.net/manual/en/class.pdo-pgsql.php)).

```php
$stmt = $pdo->prepare(
    'UPDATE accounts SET active = :active, note = :note WHERE id = ANY(CAST(:ids AS bigint[]))'
);
$stmt->bindValue(':active', false, PDO::PARAM_BOOL);
$stmt->bindValue(':note', null, PDO::PARAM_NULL);
$stmt->bindValue(':ids', '{' . implode(',', array_map('intval', $ids)) . '}');
$stmt->execute();
```

```php
for ($attempt = 1; ; $attempt++) {
    try {
        $pdo->beginTransaction();
        transfer($pdo, $from, $to, $amount);
        $pdo->commit();
        break;
    } catch (PDOException $e) {
        if ($pdo->inTransaction()) {
            $pdo->rollBack();
        }
        if ($attempt >= 3 || !in_array($e->getCode(), ['40001', '40P01'], true)) {
            throw $e;
        }
    }
}
```

## Sources

- PHP manual (checked 2026-10-27): [PDO_PGSQL driver](https://www.php.net/manual/en/ref.pdo-pgsql.php), [`Pdo\Pgsql`](https://www.php.net/manual/en/class.pdo-pgsql.php), [PDO::prepare](https://www.php.net/manual/en/pdo.prepare.php), [PDO::setAttribute](https://www.php.net/manual/en/pdo.setattribute.php), [PDOStatement::execute](https://www.php.net/manual/en/pdostatement.execute.php), [errors and error handling](https://www.php.net/manual/en/pdo.error-handling.php), [PDOException](https://www.php.net/manual/en/class.pdoexception.php), [large objects](https://www.php.net/manual/en/pdo.lobs.php)
- PostgreSQL 18 manual (checked 2026-10-27): [arrays](https://www.postgresql.org/docs/18/arrays.html), [boolean type](https://www.postgresql.org/docs/18/datatype-boolean.html)
