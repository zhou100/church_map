-- A new congregation that is a directory church found again (same name, same address;
-- see the model for the rules). Any row is a duplicate to add to CANDIDATE_DUPLICATES.
select * from {{ ref('mart_new_congregation_directory_matches') }}
