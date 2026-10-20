-- Grain: one congregation Muse found that the directory lacks (duplicates and
-- enrichments of known congregations excluded). profile_ready still needs geocoding.
select
    candidate_id,
    task,
    format,
    candidate_name,
    current_name_native,
    city,
    case when address_displayable then street_address end   as display_street_address,
    case when address_displayable then zip end              as display_zip,
    case when website_verified then official_url end        as verified_website,
    case when fb_page_linkable then facebook_page_url end   as facebook_page_url,
    case when phone_displayable then phone end              as display_phone,
    case when service_displayable then service_times end   as display_service_times,
    service_languages,
    case when kids_displayable then kids_program end        as display_kids_program,
    host_church_id,
    host_venue_name,
    muse_status,
    found_via,
    address_displayable,
    profile_ready,
    needs_geocode
from {{ ref('int_candidate_readiness') }}
where is_new_congregation
