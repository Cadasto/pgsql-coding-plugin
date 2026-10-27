---
description: Adding a required, foreign-keyed, indexed column to a large live table with goose. The migrations skill should lead to lock timeouts, NOT VALID then VALIDATE in separate migrations, a concurrent index in a no-transaction goose file, a batched backfill, and a NOT NULL constraint added only after the backfill, without a full scan under an exclusive lock.
max_turns: 12
allowed_tools: [Read, Glob, Grep, Skill]
---

We run PostgreSQL 18 and use goose for migrations (plain SQL files, default settings). The `orders` table has about 120 million rows and takes reads and writes all day; we cannot take downtime.

```sql
CREATE TABLE tenants (
    id   bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    name text NOT NULL
);

CREATE TABLE customers (
    id        bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    tenant_id bigint NOT NULL REFERENCES tenants (id)
);

CREATE TABLE orders (
    id          bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    customer_id bigint NOT NULL REFERENCES customers (id),
    total       numeric(12,2) NOT NULL,
    created_at  timestamptz NOT NULL DEFAULT now()
);
```

We need `orders.tenant_id`: required (NOT NULL), a foreign key to `tenants`, filled from each order's customer, and indexed because every query will filter on it. A teammate wrote this single goose migration:

```sql
-- +goose Up
ALTER TABLE orders ADD COLUMN tenant_id bigint;
UPDATE orders o SET tenant_id = c.tenant_id FROM customers c WHERE c.id = o.customer_id;
ALTER TABLE orders ALTER COLUMN tenant_id SET NOT NULL;
ALTER TABLE orders ADD CONSTRAINT orders_tenant_id_fkey FOREIGN KEY (tenant_id) REFERENCES tenants (id);
CREATE INDEX orders_tenant_id_idx ON orders (tenant_id);

-- +goose Down
ALTER TABLE orders DROP COLUMN tenant_id;
```

Is this safe to run in production? If not, rewrite it as the sequence of goose migration files, plus any backfill step, that we should ship instead.
