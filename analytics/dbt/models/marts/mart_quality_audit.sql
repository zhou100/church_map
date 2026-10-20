-- Grain: audited field (plus an 'all' rollup row). Owner's blind audit vs Muse.
-- Small sample: report counts, not just rates.
select
    coalesce(field, 'all')                                          as field,
    count(*)                                                        as reviewed,
    count(*) filter (where verdict = 'agree')                       as agree,
    count(*) filter (where verdict = 'disagree')                    as disagree,
    count(*) filter (where verdict = 'definition_disagreement')     as definition_disagreement,
    count(*) filter (where verdict = 'needs_review')                as needs_review,
    round(count(*) filter (where verdict = 'agree')::numeric / nullif(count(*), 0), 3) as agreement_rate,
    count(distinct church_id)                                       as churches
from {{ ref('quality_reviews') }}
group by rollup (field)
