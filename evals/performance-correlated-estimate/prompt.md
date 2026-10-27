---
description: A slow join whose plan shows a large row misestimate from two correlated filter columns. The statistics reference should lead to extended statistics plus ANALYZE, not to work_mem or an index alone.
max_turns: 12
allowed_tools: [Read, Glob, Grep, Skill]
---

This query got slow after we loaded the Dutch market's orders (orders now has about 20 million rows). We're on PostgreSQL 18. My colleague wants to either add a composite index on `orders (country, city)` or bump `work_mem`. What's actually wrong here, and what should we do?

```sql
SELECT o.id, o.total, o.created_at, c.name
FROM orders AS o
JOIN customers AS c ON c.id = o.customer_id
WHERE o.country = 'NL' AND o.city = 'Amsterdam'
ORDER BY o.created_at DESC;
```

Existing indexes: `orders_country_idx (country)`, `orders_city_idx (city)`, `customers_pkey (id)`. Autovacuum is on and `orders` was analyzed an hour ago.

```
Sort  (cost=5462.31..5463.81 rows=600 width=44) (actual time=3187.204..3192.118 rows=48210.00 loops=1)
  Sort Key: o.created_at DESC
  Sort Method: quicksort  Memory: 5642kB
  Buffers: shared hit=193512 read=12044
  ->  Nested Loop  (cost=58.71..5434.62 rows=600 width=44) (actual time=42.873..3161.540 rows=48210.00 loops=1)
        Buffers: shared hit=193512 read=12044
        ->  Bitmap Heap Scan on orders o  (cost=58.28..1366.09 rows=600 width=28) (actual time=42.551..402.775 rows=48210.00 loops=1)
              Recheck Cond: ((city = 'Amsterdam'::text) AND (country = 'NL'::text))
              Heap Blocks: exact=11702
              Buffers: shared hit=672 read=12044
              ->  BitmapAnd  (cost=58.28..58.28 rows=600 width=0) (actual time=41.204..41.205 rows=0.00 loops=1)
                    Buffers: shared hit=672
                    ->  Bitmap Index Scan on orders_city_idx  (cost=0.00..21.40 rows=50114 width=0) (actual time=6.118..6.118 rows=50114.00 loops=1)
                          Index Cond: (city = 'Amsterdam'::text)
                          Index Searches: 1
                    ->  Bitmap Index Scan on orders_country_idx  (cost=0.00..36.58 rows=240388 width=0) (actual time=33.902..33.902 rows=240388.00 loops=1)
                          Index Cond: (country = 'NL'::text)
                          Index Searches: 1
        ->  Index Scan using customers_pkey on customers c  (cost=0.43..6.78 rows=1 width=24) (actual time=0.056..0.057 rows=1.00 loops=48210)
              Index Cond: (id = o.customer_id)
              Index Searches: 48210
              Buffers: shared hit=192840
Planning Time: 0.812 ms
Execution Time: 3201.447 ms
```
