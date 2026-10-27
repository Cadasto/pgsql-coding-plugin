---
type: llm
weight: 2
---

PASS if all of these hold:
- The SQL excludes customers with `NOT EXISTS (SELECT ... FROM orders o WHERE o.customer_id = c.id ...)` or an equivalent `LEFT JOIN ... WHERE o.id IS NULL`, so a NULL `customer_id` cannot empty the result.
- The month filter is half-open: `placed_at >= $start AND placed_at < $end`, where `$end` is the first instant of the next month (computed in Go with `AddDate(0, 1, 0)` or in SQL with `+ interval '1 month'`).
- `month` (and any derived bound) is passed as a query parameter, never formatted into the SQL string.
- The rows are read with `pgx.CollectRows` (for example with `pgx.RowToStructByName`), or with a manual loop that closes the rows and checks `rows.Err()`.

FAIL if the SQL uses `NOT IN (SELECT customer_id FROM orders ...)` without filtering out NULLs, uses `BETWEEN` for the month or an inclusive end such as `<= '...-31 23:59:59'`, builds the SQL with `fmt.Sprintf` or string concatenation of values, or iterates `rows.Next()` without checking `rows.Err()`.
