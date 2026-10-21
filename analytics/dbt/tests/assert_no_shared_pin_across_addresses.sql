-- Two usable pins at the same point must be the same address as Census normalized it
-- (D-107 "137 Dempsey Rd" and CN-014 "137 Dempsey Road" share one). Different
-- addresses on one point means a centroid, not a street-segment match.
select latitude, longitude
from {{ ref('int_geocodes') }}
where pin_usable
group by latitude, longitude
having count(distinct matched_address) > 1
