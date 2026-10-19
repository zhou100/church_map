-- Grain: one church that shares a 4-decimal coordinate with 3+ other records
-- (city/ZIP centroids, bulk imports). Bounds checks cannot catch these.
with grid as (
    select church_id,
           round(latitude::numeric, 4)  as lat4,
           round(longitude::numeric, 4) as lon4
    from {{ ref('stg_churches') }}
    where latitude is not null
),
dense as (
    select lat4, lon4, count(*) as records_at_point
    from grid
    group by 1, 2
    having count(*) > 3
)
select g.church_id, d.records_at_point
from grid g
join dense d using (lat4, lon4)
