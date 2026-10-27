---
description: Index plan for a large orders table queried from a Go service. The indexing skill should lead to equality-first column order, a pattern-aware prefix index in a non-C database, an index serving the foreign key, and concurrent builds outside a transaction.
max_turns: 12
allowed_tools: [Read, Glob, Grep, Skill]
---

We run PostgreSQL 18. The database was created with `LC_COLLATE = 'en_US.UTF-8'`. The `orders` table has about 40 million rows and takes writes all day:

```sql
CREATE TABLE orders (
    id          bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    customer_id bigint NOT NULL REFERENCES customers (id),
    status      text NOT NULL,          -- 'pending', 'paid', 'shipped', 'cancelled'; about 95% are 'shipped'
    reference   text NOT NULL,          -- e.g. 'INV-2026-000123'
    created_at  timestamptz NOT NULL DEFAULT now()
);
```

It has no indexes besides the primary key. Our Go service (pgx) runs these queries:

1. `SELECT id, status, created_at FROM orders WHERE customer_id = $1 ORDER BY created_at DESC LIMIT 20`
2. `SELECT id FROM orders WHERE status = 'pending' AND created_at < now() - interval '1 hour'`
3. `SELECT id, reference FROM orders WHERE reference LIKE 'INV-2026-0001%'` (the support tool sends the prefix as a literal)

Deleting a customer is also very slow. Write the SQL migration that adds the indexes we need, and say in one line each why.
