-- D-1: hidden records (out of scope, not a congregation, pending) are never visit-ready.
select church_id
from {{ ref('int_location_readiness') }}
where visit_ready and not is_in_scope
