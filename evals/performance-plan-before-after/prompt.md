---
description: Before and after plans for an orders search, after adding an expression index on a jsonb key. The plan analyst (or the performance skill) should see that the index is never scanned, that it helped only by fixing the row estimate, and that sorts and a hash still spill and a correlated filter is still misestimated.
max_turns: 20
timeout_seconds: 600
allowed_tools: [Read, Glob, Grep, Skill, Agent]
---

Our order search got faster after I added `CREATE INDEX orders_channel_idx ON orders ((doc->>'channel'));` and ran ANALYZE, roughly 79 ms down to 52 ms. Staging has 400k orders and 50k customers on PostgreSQL 18. Here are the plans from before and after. Did the index do what I think it did, and what should I fix next?

Query:

```sql
SELECT c.city, o.status, o.id, o.total
FROM customers c JOIN orders o ON o.customer_id = c.id
WHERE c.country = 'NL' AND c.city = 'NL-city-0' AND o.doc->>'channel' = 'web'
ORDER BY o.total DESC, o.id;
```

Before:

```
Gather Merge  (cost=10322.20..10331.40 rows=79 width=30) (actual time=69.784..78.097 rows=26667.00 loops=1)
  Workers Planned: 2
  Workers Launched: 2
  Buffers: shared hit=405829, temp read=301 written=332
  ->  Sort  (cost=9322.17..9322.26 rows=33 width=30) (actual time=67.852..68.766 rows=8889.00 loops=3)
        Sort Key: o.total DESC, o.id
        Sort Method: external merge  Disk: 416kB
        Buffers: shared hit=405829, temp read=301 written=332
        Worker 0:  Sort Method: external merge  Disk: 408kB
        Worker 1:  Sort Method: external merge  Disk: 400kB
        ->  Nested Loop  (cost=0.29..9321.34 rows=33 width=30) (actual time=0.028..62.707 rows=8889.00 loops=3)
              Buffers: shared hit=405799
              ->  Parallel Seq Scan on orders o  (cost=0.00..8298.00 rows=833 width=28) (actual time=0.013..19.972 rows=44444.33 loops=3)
                    Filter: ((doc ->> 'channel'::text) = 'web'::text)
                    Rows Removed by Filter: 88889
                    Buffers: shared hit=5798
              ->  Index Scan using customers_pkey on customers c  (cost=0.29..1.23 rows=1 width=18) (actual time=0.001..0.001 rows=0.20 loops=133333)
                    Index Cond: (id = o.customer_id)
                    Filter: ((country = 'NL'::text) AND (city = 'NL-city-0'::text))
                    Rows Removed by Filter: 1
                    Index Searches: 133333
                    Buffers: shared hit=400001
Planning:
  Buffers: shared hit=142 read=2
Planning Time: 0.438 ms
Execution Time: 78.938 ms
```

After:

```
Gather Merge  (cost=10718.97..11343.70 rows=5364 width=30) (actual time=43.541..51.380 rows=26667.00 loops=1)
  Workers Planned: 2
  Workers Launched: 2
  Buffers: shared hit=6785, temp read=2045 written=2076
  ->  Sort  (cost=9718.95..9724.54 rows=2235 width=30) (actual time=41.317..42.355 rows=8889.00 loops=3)
        Sort Key: o.total DESC, o.id
        Sort Method: external merge  Disk: 400kB
        Buffers: shared hit=6785, temp read=2045 written=2076
        Worker 0:  Sort Method: external merge  Disk: 400kB
        Worker 1:  Sort Method: external merge  Disk: 424kB
        ->  Hash Join  (cost=1094.01..9538.62 rows=2235 width=30) (actual time=4.038..35.941 rows=8889.00 loops=3)
              Hash Cond: (o.customer_id = c.id)
              Buffers: shared hit=6755, temp read=1745 written=1745
              ->  Parallel Seq Scan on orders o  (cost=0.00..8298.00 rows=55845 width=28) (actual time=0.010..19.462 rows=44444.33 loops=3)
                    Filter: ((doc ->> 'channel'::text) = 'web'::text)
                    Rows Removed by Filter: 88889
                    Buffers: shared hit=5798
              ->  Hash  (cost=1069.00..1069.00 rows=2001 width=18) (actual time=3.962..3.963 rows=10000.00 loops=3)
                    Buckets: 2048 (originally 2048)  Batches: 8 (originally 1)  Memory Usage: 113kB
                    Buffers: shared hit=957, temp written=132
                    ->  Seq Scan on customers c  (cost=0.00..1069.00 rows=2001 width=18) (actual time=0.009..2.632 rows=10000.00 loops=3)
                          Filter: ((country = 'NL'::text) AND (city = 'NL-city-0'::text))
                          Rows Removed by Filter: 40000
                          Buffers: shared hit=957
Planning:
  Buffers: shared hit=165 read=3
Planning Time: 0.435 ms
Execution Time: 52.194 ms
```
