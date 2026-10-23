-- `website` feeds the crawler; a Facebook Page goes to facebook_url only (plan B1).
select 'church' as kind, church_id::text as id, website from {{ ref('mart_publish_churches') }}
 where website ~* 'facebook\.com'
union all
select 'new', external_id, website from {{ ref('mart_publish_new') }}
 where website ~* 'facebook\.com'
