-- Grain: one directory church that scripts/publish_verified.py writes to production.
-- Only facts that pass the display rule (dim_church), each with the page it came
-- from; a NULL value means "write nothing" (the publisher never blanks a field).
--   * scope: every church whose D-1 status isn't plain in_scope (the API hides the
--     out-of-scope ones; in_scope_labeled shows its tradition label);
--   * facts: only for in-scope churches;
--   * pin: a usable Census pin replaces the directory pin only where Muse saw the pin
--     at a different place and the new point is more than 50 m away (plan B2).
with d as (
    select * from {{ ref('dim_church') }}
),
m as (
    select church_id, address_source_url, phone_source_url, service_source_url, kids_source_url,
           phone_source_type, service_source_type, kids_source_type
    from {{ ref('stg_muse_results') }}
),
r as (
    select church_id, pin_check from {{ ref('int_location_readiness') }}
),
facts as (
    select
        d.church_id,
        nullif(d.scope_status, 'in_scope')                                  as scope_status,
        d.display_tradition,
        d.scope_status in ('in_scope', 'in_scope_labeled')                  as in_scope,
        d.display_street_address                                            as address,
        d.display_zip                                                       as zip_code,
        m.address_source_url,
        d.address_source_type,
        d.display_phone                                                     as phone,
        m.phone_source_url,
        case when d.display_phone is not null then m.phone_source_type end  as phone_source_type,
        d.display_service_times                                             as service_times,
        case when d.service_displayable then d.service_languages end        as service_languages,
        m.service_source_url,
        case when d.service_displayable then m.service_source_type end      as service_source_type,
        d.display_kids_program                                              as kids_program,
        m.kids_source_url,
        case when d.kids_displayable then m.kids_source_type end            as kids_source_type,
        d.verified_website                                                  as website,
        d.facebook_page_url                                                 as facebook_url,
        case when r.pin_check = 'off' and d.proposed_pin_usable and d.proposed_pin_moves_m > 50
             then d.proposed_latitude end                                   as latitude,
        case when r.pin_check = 'off' and d.proposed_pin_usable and d.proposed_pin_moves_m > 50
             then d.proposed_longitude end                                  as longitude,
        d.muse_checked_at                                                   as checked_at
    from d
    left join m using (church_id)
    left join r using (church_id)
)
select
    church_id, scope_status, display_tradition,
    case when in_scope then address end              as address,
    case when in_scope then zip_code end             as zip_code,
    case when in_scope and address is not null then address_source_url end  as address_source_url,
    case when in_scope and address is not null then address_source_type end as address_source_type,
    case when in_scope then phone end                as phone,
    case when in_scope and phone is not null then phone_source_url end      as phone_source_url,
    case when in_scope then phone_source_type end    as phone_source_type,
    case when in_scope then service_times end        as service_times,
    case when in_scope and service_times is not null then service_languages end as service_languages,
    case when in_scope and service_times is not null then service_source_url end as service_source_url,
    case when in_scope and service_times is not null then service_source_type end as service_source_type,
    case when in_scope then kids_program end         as kids_program,
    case when in_scope and kids_program is not null then kids_source_url end as kids_source_url,
    case when in_scope then kids_source_type end     as kids_source_type,
    case when in_scope then website end              as website,
    case when in_scope then facebook_url end         as facebook_url,
    case when in_scope then latitude end             as latitude,
    case when in_scope then longitude end            as longitude,
    checked_at
from facts
where scope_status is not null
   or (in_scope and coalesce(address, phone, service_times, kids_program, website, facebook_url) is not null)
   or (in_scope and latitude is not null)
