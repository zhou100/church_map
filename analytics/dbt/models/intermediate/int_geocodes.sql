-- Grain: one geocoded subject (church or candidate). A pin counts only while the
-- record still has the address it was geocoded from: a pin for 100 Main St says
-- nothing about 200 Main St, so a later correction needs a new geocode.
with g as (
    select * from {{ ref('stg_geocodes') }}
),
current_address as (
    select 'candidate' as subject_type, candidate_id as subject_id, street_address, city, zip
    from {{ ref('stg_muse_candidates') }}
    union all
    select 'church', m.church_id::text, m.street_address, coalesce(m.city, c.city), m.zip
    from {{ ref('stg_muse_results') }} m
    join {{ ref('stg_churches') }} c using (church_id)
)
select
    g.*,
    a.street_address                                                    as current_street,
    coalesce({{ address_key('g.geocoded_street', 'g.geocoded_city', 'g.geocoded_zip') }}
             = {{ address_key('a.street_address', 'a.city', 'a.zip') }}, false) as address_unchanged,
    g.geocode_status = 'ok'
        and g.latitude is not null and g.longitude is not null
        and coalesce({{ address_key('g.geocoded_street', 'g.geocoded_city', 'g.geocoded_zip') }}
                     = {{ address_key('a.street_address', 'a.city', 'a.zip') }}, false) as pin_usable
from g
left join current_address a using (subject_type, subject_id)
