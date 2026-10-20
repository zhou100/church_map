-- Grain: subject (church or candidate) x fact group. Re-verification verdicts.
select
    subject_type,
    subject_id,
    fact_group,
    verdict,
    verdict = 'verified' as is_verified,
    checked_at
from {{ ref('source_checks') }}
