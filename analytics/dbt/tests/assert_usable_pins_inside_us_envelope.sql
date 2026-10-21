-- A usable pin passes the same US envelope as the directory (stg_churches.coords_ok).
select geo_id
from {{ ref('int_geocodes') }}
where pin_usable
  and not (latitude between -15 and 72
           and (longitude between -180 and -64 or longitude between 144 and 180)
           and not (latitude = 0 and longitude = 0))
