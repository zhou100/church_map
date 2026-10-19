-- Grain: one church (one location per church until campus modeling, plan §11).
-- Combines directory flags, Muse verification, scope (D-1), personal-phone
-- removal (D-2, applied in seeds) and Facebook display rules (D-3).
with c as (
    select * from {{ ref('stg_churches') }}
),
m as (
    select * from {{ ref('stg_muse_results') }}
),
s as (
    select * from {{ ref('int_scope') }}
),
holds as (
    select church_id,
           bool_or(field = 'street_address') as hold_address,
           bool_or(field = 'service_times')  as hold_service
    from {{ ref('fact_holds') }}
    group by 1
),
asof as (
    select '{{ var("as_of_date") }}'::date as as_of_date
),
joined as (
    select
        c.church_id,
        c.source,
        m.church_id is not null                                       as in_muse_pilot,
        s.scope_status,
        s.scope_status in ('in_scope', 'in_scope_labeled')            as is_in_scope,
        c.street_text is not null                                     as has_street_text,
        c.has_house_number,
        c.has_google_address,
        (c.has_house_number or c.has_google_address)
            and c.city is not null and c.state is not null            as has_routable_directory_address,
        c.coords_ok,
        cl.church_id is not null                                      as in_repeated_cluster,
        m.muse_status,
        coalesce(m.muse_status = 'active', false)                     as verified_active,
        m.pin_check,
        coalesce(m.fb_last_post_date >= a.as_of_date - 365, false)    as fb_page_fresh,
        m.street_address is not null                                  as muse_has_address,
        m.address_source_type,
        m.phone is not null                                           as muse_has_phone,
        m.phone_source_type,
        m.service_times is not null                                   as muse_has_service,
        m.service_source_type,
        coalesce(h.hold_address, false)                               as hold_address,
        coalesce(h.hold_service, false)                               as hold_service,
        m.official_url is not null
            and coalesce(m.url_evidence, 'name_only') <> 'name_only'  as website_verified,
        m.facebook_page_url is not null and m.fb_page_evidence is not null as fb_page_linkable
    from c
    join s using (church_id)
    left join {{ ref('int_coordinate_clusters') }} cl on cl.church_id = c.church_id
    left join m on m.church_id = c.church_id
    left join holds h on h.church_id = c.church_id
    cross join asof a
),
rules as (
    select
        *,
        -- D-3: a fact may be shown when it comes from the church's own site or
        -- denomination, or from its own Page if the row is active and the Page
        -- posted within 12 months. Third-party/"other" sources need review.
        muse_has_address and not hold_address and (
            address_source_type in ('own_site', 'denomination')
            or (address_source_type = 'fb_page' and verified_active and fb_page_fresh)
        )                                                             as address_displayable,
        muse_has_phone and (
            phone_source_type in ('own_site', 'denomination')
            or (phone_source_type = 'fb_page' and verified_active and fb_page_fresh)
        )                                                             as phone_displayable,
        muse_has_service and not hold_service and (
            service_source_type in ('own_site', 'denomination')
            or (service_source_type = 'fb_page' and verified_active and fb_page_fresh)
        )                                                             as service_displayable
    from joined
)
select
    *,
    is_in_scope
        and verified_active
        and address_displayable
        and coords_ok
        and coalesce(pin_check, 'unknown') <> 'off'
        and (website_verified or (fb_page_linkable and fb_page_fresh) or phone_displayable)
                                                                      as visit_ready
from rules
