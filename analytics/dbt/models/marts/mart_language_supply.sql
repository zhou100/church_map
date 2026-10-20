-- Grain: stated service language x city x origin (directory church / new congregation).
-- Cold-start question: where can someone actually find a service in their language?
-- Languages count only as the congregation states them (N5); no inference from names.
with directory as (
    select r.church_id::text as subject_id, 'directory' as origin, coalesce(m.city, c.city) as city,
           m.service_languages, r.verified_active as active, r.service_displayable, r.kids_displayable,
           r.visit_ready as ready
    from {{ ref('int_location_readiness') }} r
    join {{ ref('stg_muse_results') }} m using (church_id)
    join {{ ref('stg_churches') }} c using (church_id)
    where r.is_in_scope and m.service_languages is not null
),
new_congregations as (
    select candidate_id, 'new_congregation', city, service_languages, verified_active,
           service_displayable, kids_displayable, profile_ready
    from {{ ref('int_candidate_readiness') }}
    where is_new_congregation and service_languages is not null
),
exploded as (
    select subject_id, origin, city, btrim(lang) as language, active, service_displayable, kids_displayable, ready
    from (select * from directory union all select * from new_congregations) u,
         regexp_split_to_table(u.service_languages, ';') as lang
)
select
    language,
    city,
    origin,
    count(*)                                         as congregations,
    count(*) filter (where active)                   as active,
    count(*) filter (where service_displayable)      as with_shown_service_times,
    count(*) filter (where kids_displayable)         as with_shown_kids_program,
    count(*) filter (where ready)                    as ready
from exploded
where language <> ''
group by 1, 2, 3
