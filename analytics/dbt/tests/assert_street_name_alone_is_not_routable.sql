-- A bare street name ("Oak Grove Avenue") must never count as a routable address.
select church_id
from {{ ref('int_location_readiness') }} r
join {{ ref('stg_churches') }} c using (church_id)
where r.has_routable_directory_address
  and not c.has_house_number
  and not c.has_google_address
