-- Grain: one congregation already published from Muse (stg_published_candidates),
-- with where its candidate stands now. The publisher only inserts and updates from
-- mart_publish_new; a published row whose candidate has since left it (no longer
-- map-ready, now a duplicate, or gone) stays on the map until someone acts on it.
-- This lists those rows; it does not decide what happens to them.
select
    p.church_id,
    p.candidate_id,
    p.published_name,
    c.candidate_id is not null                                  as candidate_found,
    coalesce(c.is_new_congregation, false)                      as is_new_congregation,
    coalesce(c.map_ready, false)                                as map_ready,
    case
        when c.candidate_id is null    then 'unknown_candidate'
        when not c.is_new_congregation then 'no_longer_new'
        when not c.map_ready           then 'no_longer_map_ready'
        else 'current'
    end                                                         as publication_status
from {{ ref('stg_published_candidates') }} p
left join {{ ref('int_candidate_readiness') }} c using (candidate_id)
