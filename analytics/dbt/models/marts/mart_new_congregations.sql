-- Grain: one congregation Muse found that the directory lacks (duplicates excluded).
select
    candidate_id,
    batch,
    candidate_name,
    current_name_native,
    street_address,
    city,
    zip,
    official_url,
    facebook_page_url,
    service_languages,
    host_church_id,
    host_venue_name,
    found_via,
    has_street_address,
    source_type in ('own_site', 'denomination')                    as officially_sourced
from {{ ref('stg_muse_candidates') }}
where is_new_congregation
