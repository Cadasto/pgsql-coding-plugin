---
description: A slow jsonb filter behind a jsonb_path_ops GIN index. The jsonb indexing reference should lead to an indexable containment predicate with a typed, bound value.
max_turns: 12
allowed_tools: [Read, Glob, Grep, Skill]
---

Our Go service uses pgx v5 against PostgreSQL 18. The table and its only secondary index:

```sql
CREATE TABLE events (
  id  bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
  doc jsonb NOT NULL
);
CREATE INDEX events_doc_idx ON events USING GIN (doc jsonb_path_ops);
```

`customer_id` is stored in `doc` as a JSON number, and `tags` is an array of strings. This call takes several seconds on 20 million rows even though we have the GIN index:

```go
rows, err := pool.Query(ctx, `
    SELECT id, doc
    FROM events
    WHERE doc->>'customer_id' = $1
      AND jsonb_path_exists(doc, '$.tags[*] ? (@ == "vip")')`,
    strconv.FormatInt(customerID, 10))
```

`customerID` is an `int64`. Rewrite the query and the Go call so the existing index is used. Keep the answer short.
