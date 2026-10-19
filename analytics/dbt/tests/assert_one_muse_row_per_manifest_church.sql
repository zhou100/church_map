-- Every manifest church has exactly one Muse verdict, and no verdict is outside the manifest.
select coalesce(m.church_id, r.church_id) as church_id
from {{ ref('muse_manifest') }} m
full outer join {{ ref('stg_muse_results') }} r using (church_id)
where m.church_id is null or r.church_id is null
