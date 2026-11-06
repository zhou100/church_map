-- Grain: one congregation scripts/publish_verified.py inserted from Muse
-- (source = 'muse', external_id = candidate_id). Kept apart from stg_churches:
-- the candidate, not the directory, owns these rows' facts.
select
    church_id,
    external_id                                              as candidate_id,
    nullif(btrim(name), '')                                  as published_name,
    latitude,
    longitude
from {{ source('raw', 'churches') }}
where source = 'muse'
