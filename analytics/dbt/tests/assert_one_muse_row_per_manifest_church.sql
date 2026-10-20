-- For every batch Muse has returned, each manifest church has exactly one verdict;
-- no verdict exists for a church outside the manifests.
with returned as (
    select distinct batch from {{ ref('muse_manifest') }} m
    join {{ ref('stg_muse_results') }} r using (church_id)
)
select m.church_id, 'missing verdict' as problem
from {{ ref('muse_manifest') }} m
join returned using (batch)
left join {{ ref('stg_muse_results') }} r using (church_id)
where r.church_id is null
union all
select r.church_id, 'not in any manifest'
from {{ ref('stg_muse_results') }} r
left join {{ ref('muse_manifest') }} m using (church_id)
where m.church_id is null
