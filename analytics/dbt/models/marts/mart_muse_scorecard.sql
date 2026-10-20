-- Grain: Muse pass that last touched a row (plus an 'all' rollup row).
with r as (
    select m.last_pass, x.*
    from {{ ref('stg_muse_results') }} m
    join {{ ref('int_location_readiness') }} x using (church_id)
)
select
    coalesce(last_pass, 'all')                                          as last_pass,
    count(*)                                                            as rows,
    count(*) filter (where muse_status = 'active')                      as active,
    count(*) filter (where muse_status = 'unresolved')                  as unresolved,
    count(*) filter (where muse_status in ('closed', 'merged'))         as closed_or_merged,
    count(*) filter (where not is_in_scope)                             as hidden_by_scope,
    count(*) filter (where muse_has_address)                            as address_found,
    count(*) filter (where address_displayable)                         as address_displayable,
    count(*) filter (where muse_has_address and not address_displayable) as address_needs_review,
    count(*) filter (where muse_has_address and address_source_type in ('own_site', 'denomination')
                       and not address_source_verified)                 as address_failed_recheck,
    count(*) filter (where phone_displayable)                           as phone_displayable,
    count(*) filter (where service_displayable)                         as service_displayable,
    count(*) filter (where fb_page_linkable)                            as fb_page_linkable,
    count(*) filter (where address_displayable and address_source_type = 'fb_page')
      + count(*) filter (where phone_displayable and phone_source_type = 'fb_page')
      + count(*) filter (where service_displayable and service_source_type = 'fb_page')
                                                                        as fb_only_facts_shown,
    count(*) filter (where visit_ready)                                 as visit_ready
from r
group by rollup (last_pass)
