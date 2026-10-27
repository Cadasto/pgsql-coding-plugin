# jsonb at the driver boundary: pgx v5 and PDO pgsql

Read when: Go code passes or scans jsonb with pgx (`pgx.Conn`, `pgxpool.Pool`, `pgtype`), including `[]byte`, `string`, `json.RawMessage`, a struct, `map[string]any`, or a custom codec; PHP code sends jsonb through PDO, or a query with `?`, `?|` or `?&` runs through PDO.

Deterministic backstop: a round-trip integration test against PostgreSQL 18 that writes and reads back a document with a large integer, a JSON `null`, an empty object and a missing key. General parameter binding, query exec modes and pooling belong to `pgsql-query`; Go error handling to `go-coding`, PHP `json_decode` flags to `php-coding`.

## pgx v5

Behaviour below was checked (versions in `## Sources`); the encode and scan rules are in [`pgtype/json.go`](https://github.com/jackc/pgx/blob/v5.11.0/pgtype/json.go) and the default registration in [`pgtype/pgtype_default.go`](https://github.com/jackc/pgx/blob/v5.11.0/pgtype/pgtype_default.go).

- **A Go `string` or `[]byte` is sent as JSON text, unchanged.** `JSONCodec.PlanEncode` passes `string`, `[]byte` and `json.RawMessage` through without marshalling. `{"a":1}` stores an object; the plain string `hello` fails with `invalid input syntax for type json` (SQLSTATE 22P02). To store a JSON string value, marshal it first: `json.Marshal("hello")` gives `"hello"`.
- **Other values go through `json.Marshal`.** Maps, structs, slices and numbers are marshalled by the codec's `Marshal` function, `json.Marshal` by default ([pgtype docs](https://pkg.go.dev/github.com/jackc/pgx/v5/pgtype)). `json.RawMessage` is passed through on purpose so it is not rewritten.
- **A struct as a containment filter includes its zero values.** `doc @> $1` with `Order{Status: "open"}` also sends `"qty": 0` and matched nothing. Build filters from a `map[string]any`, or tag optional fields `omitzero` ([encoding/json](https://pkg.go.dev/encoding/json)).
- **`map[string]any` loses large numbers.** Scanning `{"n": 12345678901234567890}` into a map gave `float64` `1.2345678901234567e+19`. Scan into a struct with typed fields or `json.RawMessage`, or register a `JSONBCodec` whose `Unmarshal` uses a `json.Decoder` with `UseNumber` ([Decoder.UseNumber](https://pkg.go.dev/encoding/json#Decoder.UseNumber)).
- **SQL NULL and JSON `null` look the same through a pointer.** Scanning SQL NULL into `*Order` gives nil, and so does `'null'::jsonb`; scanning SQL NULL into a non-pointer `Order` returns an error. When the difference matters, select `doc IS NULL` or `jsonb_typeof(doc)` as well.
- **A nil map, nil pointer or nil `json.RawMessage` becomes SQL NULL.** On a `NOT NULL` column that insert fails; send `map[string]any{}` or `json.RawMessage("{}")` when an empty document is meant.
- **Under the simple protocol, pass jsonb as a `string`.** `pgsql-query` owns the choice of mode. Only under the simple protocol, a `map[string]any` failed with `cannot find encode plan` for `unknown type (OID 0)`, and a `[]byte` arrived as the bytea literal `\x2268...`, which `$1::jsonb` rejects. There, pass `string(json.Marshal output)` and cast in SQL: `$1::jsonb`.
- **Bind values into jsonb predicates; do not format them in.** `doc @> $1` with a map, or `doc @> jsonb_build_object('status', $1::text)`, keeps the GIN index (see `indexing.md`). Never `fmt.Sprintf` a value into a JSON literal or a jsonpath.

```go
// Filter: map, so only the keys given are matched.
rows, err := pool.Query(ctx,
    `SELECT id, doc FROM orders WHERE doc @> $1`,
    map[string]any{"status": "open"})

// Scan: typed struct, so numbers keep their Go type.
var o Order // fields with json tags; use *Order when doc may be NULL
err = pool.QueryRow(ctx, `SELECT doc FROM orders WHERE id = $1`, id).Scan(&o)
```

## PDO pgsql

Behaviour below was checked (versions in `## Sources`).

- **`?`, `?|` and `?&` collide with PDO's placeholders.** Since PHP 7.4, `??` is sent to the server as `?` ([PDO::prepare](https://www.php.net/manual/en/pdo.prepare.php)): write `doc ?? :key`, `doc ?? ?` or `doc ??| CAST(:keys AS text[])`. A bare `?` operator in a statement with `:name` parameters fails with `SQLSTATE[HY093]: Invalid parameter number: mixed named and positional parameters`, because the two marker styles cannot be mixed.
- **Bind the document as text and cast in SQL.** Bind `json_encode($value, JSON_THROW_ON_ERROR)` and write `CAST(:doc AS jsonb)` (or `:doc::jsonb`, which PDO also parses correctly). For filters, bind the encoded object to `doc @> CAST(:filter AS jsonb)`.
- **jsonb comes back as a string.** `fetch` returned the JSON text, so a large integer survives until `json_decode` turns it into a float; pass `JSON_BIGINT_AS_STRING` when that matters ([json_decode](https://www.php.net/manual/en/function.json-decode.php)).

```php
$stmt = $pdo->prepare(
    'SELECT id FROM orders WHERE doc ?? :key AND doc @> CAST(:filter AS jsonb)'
);
$stmt->execute([
    'key'    => 'refund',
    'filter' => json_encode(['status' => 'open'], JSON_THROW_ON_ERROR),
]);
```

## Sources

- pgx v5.11.0 `pgtype/json.go` (encode plans for string, []byte, json.RawMessage; pointer scan of JSON null): <https://github.com/jackc/pgx/blob/v5.11.0/pgtype/json.go> (checked 2026-10-27)
- pgx v5.11.0 `pgtype/pgtype_default.go` (`JSONBCodec{Marshal: json.Marshal, Unmarshal: json.Unmarshal}`): <https://github.com/jackc/pgx/blob/v5.11.0/pgtype/pgtype_default.go> (checked 2026-10-27)
- pgtype package docs (JSON support, NULL handling): <https://pkg.go.dev/github.com/jackc/pgx/v5/pgtype> (checked 2026-10-27)
- Go `encoding/json` (`omitzero`, `Decoder.UseNumber`): <https://pkg.go.dev/encoding/json> (checked 2026-10-27)
- PHP manual, PDO::prepare (`??` escape, marker styles): <https://www.php.net/manual/en/pdo.prepare.php> (checked 2026-10-27)
- PHP manual, json_decode (big integers decode to float; `JSON_BIGINT_AS_STRING`): <https://www.php.net/manual/en/function.json-decode.php> (checked 2026-10-27)
- Behaviour marked "checked" was run with pgx v5.11.0, PHP 8.4.27 with `pdo_pgsql`, and PostgreSQL 18.6 (2026-10-27).
