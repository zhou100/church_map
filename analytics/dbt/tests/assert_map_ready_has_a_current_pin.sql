-- map_ready needs a complete profile and a pin geocoded from the address it has now;
-- a pin for an address the record no longer has never counts.
select candidate_id
from {{ ref('int_candidate_readiness') }}
where map_ready
  and not (profile_ready and pin_usable and latitude is not null and longitude is not null)
union all
select g.subject_id
from {{ ref('int_geocodes') }} g
where g.pin_usable and not g.address_unchanged
