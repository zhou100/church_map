-- Grain: one congregation Muse found that the directory lacks, ready for the map
-- (map_ready: a complete profile on evidence that holds up, and a Census pin of its
-- current address). scripts/publish_verified.py inserts it with source = 'muse' and
-- external_id = candidate_id, or updates the row a previous run inserted.
select
    n.candidate_id                                                   as external_id,
    n.candidate_name                                                 as name,
    c.denomination_stated                                            as denomination,
    n.display_street_address                                         as address,
    n.city,
    'CA'                                                             as state,
    n.display_zip                                                    as zip_code,
    n.latitude,
    n.longitude,
    c.address_source_url,
    c.address_source_type,
    n.display_phone                                                  as phone,
    case when n.display_phone is not null then c.phone_source_url end  as phone_source_url,
    case when n.display_phone is not null then c.phone_source_type end as phone_source_type,
    n.display_service_times                                          as service_times,
    case when n.display_service_times is not null then n.service_languages end   as service_languages,
    case when n.display_service_times is not null then c.service_source_url end  as service_source_url,
    case when n.display_service_times is not null then c.service_source_type end as service_source_type,
    n.display_kids_program                                           as kids_program,
    case when n.display_kids_program is not null then c.kids_source_url end  as kids_source_url,
    case when n.display_kids_program is not null then c.kids_source_type end as kids_source_type,
    n.verified_website                                               as website,
    n.facebook_page_url                                              as facebook_url,
    c.status_source_url,
    c.status_source_type,
    c.checked_at
from {{ ref('mart_new_congregations') }} n
join {{ ref('stg_muse_candidates') }} c using (candidate_id)
where n.map_ready
