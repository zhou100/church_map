-- D-2: a phone flagged as personal is never kept, let alone displayed.
select r.church_id
from {{ ref('stg_muse_results') }} r
join {{ ref('dim_church') }} d using (church_id)
where r.personal_phone_withheld and (r.phone is not null or d.display_phone is not null)
