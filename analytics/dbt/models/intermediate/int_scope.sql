-- Grain: one church. Decision D-1: what the map shows.
-- Precedence: Muse's verdict on the named entity > denomination mapping >
-- name pattern (religious houses) > default in_scope. A Muse-confirmed duplicate
-- record is hidden in favour of the record it duplicates.
with base as (
    select
        c.church_id,
        c.osm_name,
        c.denomination,
        ds.scope_status      as denomination_scope,
        ds.display_tradition,
        c.osm_name ~* '(convent|monastery|abbey|motherhouse|^sisters of)' as name_is_religious_house,
        m.entity_type        as muse_entity_type,
        m.duplicate_of_church_id
    from {{ ref('stg_churches') }} c
    left join {{ ref('denomination_scope') }} ds
        on ds.denomination_key = lower(c.denomination)
    left join {{ ref('stg_muse_results') }} m
        on m.church_id = c.church_id
)
select
    church_id,
    case
        when duplicate_of_church_id is not null                      then 'duplicate'
        when muse_entity_type = 'non_christian'                      then 'out_of_scope'
        when muse_entity_type in ('religious_house', 'business')     then 'not_a_congregation'
        when muse_entity_type = 'unknown'                            then 'pending'
        when denomination_scope is not null                          then denomination_scope
        when name_is_religious_house                                 then 'not_a_congregation'
        else 'in_scope'
    end as scope_status,
    display_tradition,
    case
        when duplicate_of_church_id is not null                      then 'muse'
        when muse_entity_type is not null and muse_entity_type <> 'congregation' then 'muse'
        when denomination_scope is not null                          then 'denomination'
        when name_is_religious_house                                 then 'name_pattern'
        when muse_entity_type = 'congregation'                       then 'muse'
        else 'default'
    end as scope_basis
from base
