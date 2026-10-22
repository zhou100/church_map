{#
  One comparable key for a street address: case and spacing ignored, nothing else.
  A pin or an answer bound to an address stops counting once this key changes.
#}
{% macro address_key(street, city, zip) -%}
lower(regexp_replace(btrim(coalesce({{ street }}, '') || '|' || coalesce({{ city }}, '') || '|' || coalesce({{ zip }}, '')), '\s+', ' ', 'g'))
{%- endmacro %}
