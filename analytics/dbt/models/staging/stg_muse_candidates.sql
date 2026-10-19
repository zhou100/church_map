-- Grain: one congregation Muse reported as missing from the manifest.
select
    candidate_id,
    batch,
    candidate_name,
    nullif(current_name_native, '')                          as current_name_native,
    nullif(street_address, '')                               as street_address,
    nullif(city, '')                                         as city,
    nullif(zip, '')                                          as zip,
    nullif(official_url, '')                                 as official_url,
    nullif(facebook_page_url, '')                            as facebook_page_url,
    nullif(service_languages, '')                            as service_languages,
    host_church_id,
    nullif(host_venue_name, '')                              as host_venue_name,
    duplicate_of_church_id,
    source_type,
    found_via,
    street_address is not null and street_address <> ''     as has_street_address,
    duplicate_of_church_id is null                           as is_new_congregation
from {{ ref('muse_candidates') }}
