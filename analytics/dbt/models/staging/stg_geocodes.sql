-- Grain: one Census geocode per subject (analytics/exports/geocode_output.csv, via
-- build_seeds.py), with the address it was geocoded from.
select
    geo_id,
    subject_type,
    subject_id,
    status                                                   as geocode_status,
    latitude,
    longitude,
    nullif(match_type, '')                                   as match_type,
    nullif(matched_address, '')                              as matched_address,
    nullif(tiger_line_id, '')                                as tiger_line_id,
    distance_from_current_pin_m,
    geocoded_at,
    nullif(geocoded_street, '')                              as geocoded_street,
    nullif(geocoded_city, '')                                as geocoded_city,
    nullif(geocoded_zip, '')                                 as geocoded_zip,
    input_sha256
from {{ ref('geocodes') }}
