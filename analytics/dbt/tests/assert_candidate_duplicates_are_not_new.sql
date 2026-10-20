-- A candidate marked as a duplicate or an enrichment never counts as a new congregation.
select candidate_id
from {{ ref('mart_new_congregations') }} n
join {{ ref('stg_muse_candidates') }} c using (candidate_id)
where c.duplicate_of_church_id is not null
   or c.possible_match_church_id is not null
   or c.possible_match_candidate_id is not null
