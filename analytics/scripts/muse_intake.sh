#!/usr/bin/env bash
# Ingest Muse return files: validate -> re-check sources -> rebuild seeds -> dbt build.
#
#   analytics/scripts/muse_intake.sh results_C.csv new_candidates_C.csv [--received-at 2026-10-21T18:00:00Z]
#
# File names are looked up in muse_handoff/returns/ unless a path is given. Stops on
# validator errors: those go back to Muse, not into the seeds.
set -euo pipefail
cd "$(dirname "$0")/../.."

received=()
files=()
while (($#)); do
    case "$1" in
        --received-at) received=(--received-at "$2"); shift 2 ;;
        *) f="$1"; [[ -f "$f" ]] || f="muse_handoff/returns/$1"; files+=("$f"); shift ;;
    esac
done
((${#files[@]})) || { echo "usage: $0 <return file>... [--received-at UTC]"; exit 2; }

echo "== 1/4 validate"
for f in "${files[@]}"; do
    name=$(basename "$f" .csv)
    case "$name" in
        results_E)                 args=(ALL "$f" - --redo) ;;
        results_[A-Z])             b=${name#results_}; args=("${b}_main" "$f" - --manifest "muse_handoff/batch_${b}_manifest.csv") ;;
        new_candidates_*)          args=(ALL - "$f") ;;
        *)                         echo "  skip: don't know how to validate $f"; continue ;;
    esac
    echo "-- $f"
    python3 -I muse_handoff/validate_returns.py "${args[@]}" "${received[@]}" | grep -E "^ERROR|errors," || true
    python3 -I muse_handoff/validate_returns.py "${args[@]}" "${received[@]}" >/dev/null \
        || { echo "Validator errors in $f: send them back to Muse before ingesting."; exit 1; }
done

echo "== 2/4 re-check cited sources (network, polite; takes a few minutes)"
analytics/.venv/bin/python analytics/scripts/recheck_sources.py "${files[@]}"

echo "== 3/4 rebuild seeds"
python3 analytics/scripts/build_seeds.py

echo "== 4/4 dbt build"
pg_isready -h localhost -p 5433 -q || /usr/lib/postgresql/14/bin/pg_ctl -D analytics/.pgdata \
    -o "-p 5433 -k $PWD/analytics/.pgdata -c listen_addresses=localhost" -l analytics/.pgdata/server.log start
until pg_isready -h localhost -p 5433 -q; do :; done
DBT_PROFILES_DIR=analytics/dbt analytics/.venv/bin/dbt build --project-dir analytics/dbt --full-refresh | grep -E "ERROR|FAIL|Done\."
