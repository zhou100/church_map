{#
  When may a Muse fact be shown? One rule for directory churches and new congregations:
  - from the church's own site or its denomination, and our re-check found the excerpt; or
  - (D-3) from its own Facebook Page, the subject is active and the Page posted within 12 months.
  "other" sources (aggregators, registries) need review. Holds always win.
#}
{% macro displayable(has_fact, source_type, verified, active, fb_fresh, hold='false') -%}
(
    {{ has_fact }} and not {{ hold }} and (
        ({{ source_type }} in ('own_site', 'denomination') and {{ verified }})
        or ({{ source_type }} = 'fb_page' and {{ active }} and {{ fb_fresh }})
    )
)
{%- endmacro %}
