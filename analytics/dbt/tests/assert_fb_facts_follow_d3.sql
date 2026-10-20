-- D-3: a Facebook-only fact is shown only for an active subject whose Page posted
-- within 12 months, and never when the fact is on hold. Churches and new congregations.
select church_id::text as subject_id
from {{ ref('int_location_readiness') }}
where (address_displayable and address_source_type = 'fb_page' and not (verified_active and fb_page_fresh))
   or (phone_displayable   and phone_source_type   = 'fb_page' and not (verified_active and fb_page_fresh))
   or (service_displayable and service_source_type = 'fb_page' and not (verified_active and fb_page_fresh))
   or (kids_displayable    and kids_source_type    = 'fb_page' and not (verified_active and fb_page_fresh))
   or (address_displayable and hold_address)
   or (service_displayable and hold_service)
union all
select candidate_id
from {{ ref('int_candidate_readiness') }}
where (address_displayable and address_source_type = 'fb_page' and not (verified_active and fb_page_fresh))
   or (phone_displayable   and phone_source_type   = 'fb_page' and not (verified_active and fb_page_fresh))
   or (service_displayable and service_source_type = 'fb_page' and not (verified_active and fb_page_fresh))
   or (kids_displayable    and kids_source_type    = 'fb_page' and not (verified_active and fb_page_fresh))
