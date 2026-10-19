-- Grain: one directory record (church_id). Light cleanup only.
select
    church_id,
    nullif(btrim(name), '')                                  as osm_name,
    nullif(btrim(address), '')                               as street_text,
    coalesce(address ~ '^\s*[0-9]', false)                   as has_house_number,
    coalesce(has_google_address, false)                      as has_google_address,
    nullif(btrim(city), '')                                  as city,
    nullif(btrim(state), '')                                 as state,
    nullif(btrim(zip_code), '')                              as zip,
    latitude,
    longitude,
    coalesce(
        latitude between -15 and 72
        and (longitude between -180 and -64 or longitude between 144 and 180)
        and not (latitude = 0 and longitude = 0),
        false)                                               as coords_ok,
    nullif(btrim(website), '')                               as website,
    nullif(btrim(phone), '')                                 as phone,
    coalesce(source, 'unknown')                              as source,
    external_id,
    nullif(btrim(denomination), '')                          as denomination
from {{ source('raw', 'churches') }}
