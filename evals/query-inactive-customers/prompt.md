---
description: A Go and pgx v5 report of customers with no orders in a month, where orders.customer_id is nullable. The idioms reference should lead to NOT EXISTS and a half-open timestamptz range.
max_turns: 12
allowed_tools: [Read, Glob, Grep, Skill]
---

We run PostgreSQL 18 and Go with pgx v5 (`*pgxpool.Pool`). Schema:

```sql
CREATE TABLE customers (
  id   bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
  name text NOT NULL
);
CREATE TABLE orders (
  id          bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
  customer_id bigint REFERENCES customers (id),
  placed_at   timestamptz NOT NULL
);
```

Orders imported from the old shop have `customer_id` set to NULL.

Write `func InactiveCustomers(ctx context.Context, db *pgxpool.Pool, month time.Time) ([]Customer, error)` that returns the customers who placed no order in that calendar month. `month` is the first instant of the month in UTC. `Customer` has `ID int64` and `Name string`. Sort by name. Just show me the Go code with the SQL.
