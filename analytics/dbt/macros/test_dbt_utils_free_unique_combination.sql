{% test dbt_utils_free_unique_combination(model, combination) %}
-- Fails for each combination value that appears more than once (no package needed).
select {{ combination }} as combo, count(*) as n
from {{ model }}
group by 1
having count(*) > 1
{% endtest %}
