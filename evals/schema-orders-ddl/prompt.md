---
description: DDL for customers and orders with money, timestamps, a status set that changes, and cascade-on-erasure. The types and constraints references should lead to identity keys, numeric, timestamptz, a non-enum status, and an indexed foreign key.
max_turns: 12
allowed_tools: [Read, Glob, Grep, Skill]
---

We're on PostgreSQL 18. Write the CREATE TABLE statements (and anything else the schema needs) for two tables:

- `customer`: an id, an email, and when the customer signed up.
- `customer_order`: an id, the customer it belongs to, the amount charged, the currency (EUR, USD or GBP for now), a status, and when the order was placed.

Statuses today are `pending`, `paid`, `refunded` and `cancelled`. Product has said some of these will be renamed or retired next year and new ones added. When we erase a customer for a GDPR request, all of their orders must go with them, and that erase runs from an admin screen so it needs to be quick even with millions of orders. Just give me the SQL.
