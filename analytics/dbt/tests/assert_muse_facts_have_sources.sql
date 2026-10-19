-- Every fact Muse reports carries a source URL and type.
select church_id, 'address' as fact
from {{ ref('stg_muse_results') }}
where street_address is not null and (address_source_url is null or address_source_type is null)
union all
select church_id, 'phone'
from {{ ref('stg_muse_results') }}
where phone is not null and (phone_source_url is null or phone_source_type is null)
union all
select church_id, 'service'
from {{ ref('stg_muse_results') }}
where service_times is not null and (service_source_url is null or service_source_type is null)
