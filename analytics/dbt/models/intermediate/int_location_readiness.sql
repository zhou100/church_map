-- Grain: one church (one location per church until campus modeling, plan §11).
-- Combines directory flags, Muse verification, scope (D-1), personal-phone
-- removal (D-2, applied in seeds), Facebook display rules (D-3) and the
-- source re-check (macro displayable).
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
checks as (
    select subject_id::bigint as church_id,
           bool_or(fact_group = 'status'  and is_verified) as status_source_verified,
           bool_or(fact_group = 'address' and is_verified) as address_source_verified,
           bool_or(fact_group = 'phone'   and is_verified) as phone_source_verified,
           bool_or(fact_group = 'service' and is_verified) as service_source_verified,
           bool_or(fact_group = 'kids'    and is_verified) as kids_source_verified
    from {{ ref('stg_source_checks') }}
    where subject_type = 'church'
    group by 1
),
asof as (
    select '{{ var("as_of_date") }}'::date as as_of_date
),
pins as (
    select subject_id::bigint as church_id, pin_usable, latitude, longitude, distance_from_current_pin_m
    from {{ ref('int_geocodes') }}
    where subject_type = 'church'
),
joined as (
    select
        c.church_id,
        c.source,
        m.church_id is not null                                       as in_muse,
        m.muse_batch,
        coalesce(m.muse_batch in ('A_calibration', 'B_main'), false)  as in_muse_pilot,
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
        -- Active only on evidence that holds up: the dated activity quote re-verified on
        -- the church's own page or its denomination's, or (D-3) the church's own Facebook
        -- Page with a post in the last 12 months. Muse's label alone is not enough: 78
        -- map-ready congregations had a quote our re-check could not find.
        coalesce({{ displayable("m.muse_status = 'active'", 'm.status_source_type',
                                  'coalesce(k.status_source_verified, false)', 'true',
                                  'coalesce(m.fb_last_post_date >= a.as_of_date - 365, false)') }}, false)
                                                                         as verified_active,
        m.pin_check,
        m.address_is_worship_location,
        coalesce(m.fb_last_post_date >= a.as_of_date - 365, false)    as fb_page_fresh,
        m.street_address is not null                                  as muse_has_address,
        m.address_source_type,
        m.phone is not null                                           as muse_has_phone,
        m.phone_source_type,
        m.service_times is not null                                   as muse_has_service,
        m.service_source_type,
        m.kids_program is not null                                    as muse_has_kids,
        m.kids_source_type,
        coalesce(h.hold_address, false)                               as hold_address,
        coalesce(h.hold_service, false)                               as hold_service,
        coalesce(k.address_source_verified, false)                    as address_source_verified,
        coalesce(k.phone_source_verified, false)                      as phone_source_verified,
        coalesce(k.service_source_verified, false)                    as service_source_verified,
        coalesce(k.kids_source_verified, false)                       as kids_source_verified,
        m.official_url is not null
            and coalesce(m.url_evidence, 'name_only') <> 'name_only'  as website_verified,
        m.facebook_page_url is not null and m.fb_page_evidence is not null as fb_page_linkable,
        -- A Census pin for the verified address: proposed only. How it replaces the
        -- directory pin is decided at publishing (geocode_and_publish_plan.md B2).
        coalesce(p.pin_usable, false)                                 as proposed_pin_usable,
        case when p.pin_usable then p.latitude end                    as proposed_latitude,
        case when p.pin_usable then p.longitude end                   as proposed_longitude,
        case when p.pin_usable then p.distance_from_current_pin_m end as proposed_pin_moves_m
    from c
    join s using (church_id)
    left join {{ ref('int_coordinate_clusters') }} cl on cl.church_id = c.church_id
    left join m on m.church_id = c.church_id
    left join holds h on h.church_id = c.church_id
    left join checks k on k.church_id = c.church_id
    left join pins p on p.church_id = c.church_id
    cross join asof a
),
rules as (
    select
        *,
        {{ displayable('muse_has_address', 'address_source_type', 'address_source_verified', 'verified_active', 'fb_page_fresh', 'hold_address') }} as address_displayable,
        {{ displayable('muse_has_phone',   'phone_source_type',   'phone_source_verified',   'verified_active', 'fb_page_fresh') }}                 as phone_displayable,
        {{ displayable('muse_has_service', 'service_source_type', 'service_source_verified', 'verified_active', 'fb_page_fresh', 'hold_service') }} as service_displayable,
        {{ displayable('muse_has_kids',    'kids_source_type',    'kids_source_verified',    'verified_active', 'fb_page_fresh') }}                 as kids_displayable
    from joined
)
select
    *,
    is_in_scope
        and verified_active
        and address_displayable
        -- The address must be where they meet. "no" (office, mailing) and "unknown"
        -- stay contact addresses: shown on the profile, not offered as a place to visit.
        and coalesce(address_is_worship_location, '') = 'yes'
        and coords_ok
        and coalesce(pin_check, 'unknown') <> 'off'
        and (website_verified or (fb_page_linkable and fb_page_fresh) or phone_displayable)
                                                                      as visit_ready
from rules
