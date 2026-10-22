-- A "new" congregation with the same name as a directory church at the same address
-- is that church found again (C-030 = 76688, C-064 = 77437), not a second pin. Same
-- address: the same street and city as recorded, or the same Census-matched address.
-- The directory side counts both its verified address and its raw directory address:
-- most directory churches have no Muse result, so a verified address alone misses them.
-- Different names at one address are guests sharing a building and are fine.
-- Keys are computed per side first so the join is an equi-join on the name key.
-- Must be empty (tests/assert_new_congregations_are_not_in_the_directory.sql).
with n as (
    select n.candidate_id,
           lower(regexp_replace(n.candidate_name, '[^[:alnum:]]', '', 'g'))                as name_key,
           case when n.display_street_address is not null
                then {{ address_key('n.display_street_address', 'n.city', 'null') }} end  as addr_key,
           g.matched_address
    from {{ ref('mart_new_congregations') }} n
    left join {{ ref('int_geocodes') }} g
        on g.subject_type = 'candidate' and g.subject_id = n.candidate_id and g.pin_usable
),
d_names as (
    select church_id, lower(regexp_replace(display_name, '[^[:alnum:]]', '', 'g')) as name_key
    from {{ ref('dim_church') }}
    union
    select church_id, lower(regexp_replace(osm_name, '[^[:alnum:]]', '', 'g'))
    from {{ ref('dim_church') }}
    where osm_name is not null
),
d as (
    select dn.church_id, dn.name_key,
           case when c.display_street_address is not null
                then {{ address_key('c.display_street_address', 'c.city', 'null') }} end  as addr_key,
           case when s.street_text is not null
                then {{ address_key('s.street_text', 's.city', 'null') }} end            as raw_addr_key,
           g.matched_address
    from d_names dn
    join {{ ref('dim_church') }} c using (church_id)
    join {{ ref('stg_churches') }} s using (church_id)
    left join {{ ref('int_geocodes') }} g
        on g.subject_type = 'church' and g.subject_id = c.church_id::text and g.pin_usable
    where dn.name_key in (select name_key from n)
)
select n.candidate_id,
       d.church_id,
       case when n.addr_key = d.addr_key then 'verified_address'
            when n.addr_key = d.raw_addr_key then 'directory_address'
            else 'census_match' end                                             as matched_on
from n
join d using (name_key)
where n.addr_key = d.addr_key or n.addr_key = d.raw_addr_key or n.matched_address = d.matched_address
