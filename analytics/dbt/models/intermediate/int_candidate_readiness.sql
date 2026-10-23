-- Grain: one candidate congregation (outside the directory). Same display rules as
-- churches (macro displayable). Candidates have no coordinates of their own: a
-- profile can be complete, but a pin needs a Census geocode of its current address
-- (int_geocodes.pin_usable) before it can go on the map.
with cand as (
    select * from {{ ref('stg_muse_candidates') }}
),
checks as (
    select subject_id as candidate_id,
           bool_or(fact_group = 'status'  and is_verified) as status_source_verified,
           bool_or(fact_group = 'address' and is_verified) as address_source_verified,
           bool_or(fact_group = 'phone'   and is_verified) as phone_source_verified,
           bool_or(fact_group = 'service' and is_verified) as service_source_verified,
           bool_or(fact_group = 'kids'    and is_verified) as kids_source_verified
    from {{ ref('stg_source_checks') }}
    where subject_type = 'candidate'
    group by 1
),
asof as (
    select '{{ var("as_of_date") }}'::date as as_of_date
),
pins as (
    select subject_id as candidate_id, geocode_status, pin_usable, latitude, longitude
    from {{ ref('int_geocodes') }}
    where subject_type = 'candidate'
),
joined as (
    select
        cand.*,
        p.geocode_status,
        coalesce(p.pin_usable, false)                                    as pin_usable,
        case when p.pin_usable then p.latitude end                       as latitude,
        case when p.pin_usable then p.longitude end                      as longitude,
        -- Active only on evidence that holds up: the dated activity quote re-verified on
        -- the church's own page or its denomination's, or (D-3) the church's own Facebook
        -- Page with a post in the last 12 months. Muse's label alone is not enough: 78
        -- map-ready congregations had a quote our re-check could not find.
        coalesce({{ displayable("cand.muse_status = 'active'", 'cand.status_source_type',
                                  'coalesce(k.status_source_verified, false)', 'true',
                                  'coalesce(cand.fb_last_post_date >= a.as_of_date - 365, false)') }}, false)
                                                                         as verified_active,
        coalesce(cand.fb_last_post_date >= a.as_of_date - 365, false)    as fb_page_fresh,
        coalesce(k.address_source_verified, false)                       as address_source_verified,
        coalesce(k.phone_source_verified, false)                         as phone_source_verified,
        coalesce(k.service_source_verified, false)                       as service_source_verified,
        coalesce(k.kids_source_verified, false)                          as kids_source_verified,
        cand.official_url is not null
            and coalesce(cand.url_evidence, 'name_only') <> 'name_only'  as website_verified,
        cand.facebook_page_url is not null and cand.fb_page_evidence is not null as fb_page_linkable
    from cand
    left join checks k using (candidate_id)
    left join pins p using (candidate_id)
    cross join asof a
),
rules as (
    select
        *,
        {{ displayable('street_address is not null', 'address_source_type', 'address_source_verified', 'verified_active', 'fb_page_fresh') }} as address_displayable,
        {{ displayable('phone is not null',          'phone_source_type',   'phone_source_verified',   'verified_active', 'fb_page_fresh') }} as phone_displayable,
        {{ displayable('service_times is not null',  'service_source_type', 'service_source_verified', 'verified_active', 'fb_page_fresh') }} as service_displayable,
        {{ displayable('kids_program is not null',   'kids_source_type',    'kids_source_verified',    'verified_active', 'fb_page_fresh') }} as kids_displayable
    from joined
),
ready as (
    select
        *,
        -- Ready for a profile: new, active, a displayable address and a way to reach them.
        is_new_congregation
            and verified_active
            and address_displayable
            and coalesce(address_is_worship_location, '') = 'yes'   -- where they meet, not an office
            and (website_verified or (fb_page_linkable and fb_page_fresh) or phone_displayable)
                                                                         as profile_ready
    from rules
)
select
    *,
    profile_ready and pin_usable                                         as map_ready,
    not pin_usable                                                       as needs_geocode
from ready
