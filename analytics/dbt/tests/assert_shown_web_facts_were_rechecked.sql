-- A fact from a website or denomination source is shown only if our re-check
-- found the cited excerpt on that page (the control that replaced human audit).
select church_id::text as subject_id
from {{ ref('int_location_readiness') }}
where (address_displayable and address_source_type <> 'fb_page' and not address_source_verified)
   or (phone_displayable   and phone_source_type   <> 'fb_page' and not phone_source_verified)
   or (service_displayable and service_source_type <> 'fb_page' and not service_source_verified)
   or (kids_displayable    and kids_source_type    <> 'fb_page' and not kids_source_verified)
union all
select candidate_id
from {{ ref('int_candidate_readiness') }}
where (address_displayable and address_source_type <> 'fb_page' and not address_source_verified)
   or (phone_displayable   and phone_source_type   <> 'fb_page' and not phone_source_verified)
   or (service_displayable and service_source_type <> 'fb_page' and not service_source_verified)
   or (kids_displayable    and kids_source_type    <> 'fb_page' and not kids_source_verified)
