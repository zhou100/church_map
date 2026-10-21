-- Batch, pass and task labels are the lettered rounds or a Drive work package (WP0001).
select 'muse_batch' as col, muse_batch as label
from {{ ref('stg_muse_results') }}
where muse_batch not in ('A_calibration', 'B_main', 'C_main', 'D_main', 'F_main')
  and muse_batch !~ '^WP[0-9]{4}$'
union all
select 'last_pass', last_pass
from {{ ref('stg_muse_results') }}
where last_pass not in ('A', 'A_redo', 'A_fbcheck', 'B', 'FB1', 'E', 'C', 'D', 'F', 'H')
  and last_pass !~ '^WP[0-9]{4}$'
union all
select 'task', task
from {{ ref('stg_muse_candidates') }}
where task not in ('A', 'B', 'CN', 'C', 'D', 'E', 'F', 'L', 'H')
  and task !~ '^WP[0-9]{4}$'
