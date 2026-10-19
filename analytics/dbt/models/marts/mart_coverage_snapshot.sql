-- Grain: geo_scope x source, for one snapshot. The map-readiness funnel.
-- geo_scope 'national' = every record; 'peninsula_pilot' = the 77-row Muse manifest.
with r as (
    select *, 'national' as geo_scope from {{ ref('int_location_readiness') }}
    union all
    select *, 'peninsula_pilot' as geo_scope from {{ ref('int_location_readiness') }} where in_muse_pilot
),
meta as (
    select snapshot_source, snapshot_taken_at from {{ source('raw', 'snapshot_meta') }}
)
select
    r.geo_scope,
    r.source,
    count(*)                                                    as records,
    count(*) filter (where is_in_scope)                         as in_scope,
    count(*) filter (where scope_status = 'in_scope_labeled')   as in_scope_labeled,
    count(*) filter (where not is_in_scope)                     as hidden_by_scope,
    count(*) filter (where has_street_text)                     as street_text,
    count(*) filter (where has_house_number)                    as house_numbered,
    count(*) filter (where has_routable_directory_address)      as routable_directory_address,
    count(*) filter (where coords_ok)                           as coords_ok,
    count(*) filter (where in_repeated_cluster)                 as in_repeated_cluster,
    count(*) filter (where verified_active)                     as verified_active,
    count(*) filter (where address_displayable)                 as verified_address,
    count(*) filter (where visit_ready)                         as visit_ready,
    meta.snapshot_source,
    meta.snapshot_taken_at,
    '{{ var("as_of_date") }}'::date                             as as_of_date
from r
cross join meta
group by r.geo_scope, r.source, meta.snapshot_source, meta.snapshot_taken_at
