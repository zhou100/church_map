-- Visit-ready (directory) and profile-ready (new congregations) only where the
-- address is stated to be the worship location. An office or mailing address, or an
-- unknown one, can be shown as contact information but is never offered as a visit.
select church_id::text as subject_id
from {{ ref('int_location_readiness') }}
where visit_ready and coalesce(address_is_worship_location, '') <> 'yes'
union all
select candidate_id
from {{ ref('int_candidate_readiness') }}
where profile_ready and coalesce(address_is_worship_location, '') <> 'yes'
