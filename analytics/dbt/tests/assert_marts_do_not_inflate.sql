-- Joins must not multiply rows: dim_church has exactly one row per directory record,
-- and the national funnel adds up to the directory.
select 'dim_church' as check_name
where (select count(*) from {{ ref('dim_church') }}) <> (select count(*) from {{ ref('stg_churches') }})
union all
select 'coverage_national'
where (select sum(records) from {{ ref('mart_coverage_snapshot') }} where geo_scope = 'national')
   <> (select count(*) from {{ ref('stg_churches') }})
