-- Every published fact has the page it came from (church_fact_sources needs it).
select 'church' as kind, church_id::text as id, field from (
    select church_id, 'address' as field from {{ ref('mart_publish_churches') }} where address is not null and address_source_url is null
    union all select church_id, 'phone' from {{ ref('mart_publish_churches') }} where phone is not null and phone_source_url is null
    union all select church_id, 'service_times' from {{ ref('mart_publish_churches') }} where service_times is not null and service_source_url is null
    union all select church_id, 'kids_program' from {{ ref('mart_publish_churches') }} where kids_program is not null and kids_source_url is null
) c
union all
select 'new', external_id, field from (
    select external_id, 'address' as field from {{ ref('mart_publish_new') }} where address is not null and address_source_url is null
    union all select external_id, 'phone' from {{ ref('mart_publish_new') }} where phone is not null and phone_source_url is null
    union all select external_id, 'service_times' from {{ ref('mart_publish_new') }} where service_times is not null and service_source_url is null
    union all select external_id, 'kids_program' from {{ ref('mart_publish_new') }} where kids_program is not null and kids_source_url is null
) n
