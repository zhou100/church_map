#!/usr/bin/env bash
# Hourly Drive pull, started by Windows Task Scheduler (task "ChurchMapMusePull"):
#
#   conhost.exe --headless wsl.exe -d Ubuntu -u root -- bash <repo>/muse_handoff/drive_pull_hourly.sh
#
# As root it only mounts Google Drive for desktop (G:) if WSL lost the mount, then
# re-runs itself as the repo owner. Output goes to muse_handoff/returns/drive_pull.log.
set -uo pipefail
REPO="$(cd "$(dirname "$0")/.." && pwd)"
OWNER="$(stat -c %U "$REPO")"

if [[ $(id -u) == 0 ]]; then
    if ! mountpoint -q /mnt/g; then
        mkdir -p /mnt/g
        mount -t drvfs G: /mnt/g -o "uid=$(id -u "$OWNER"),gid=$(id -g "$OWNER")" || true
    fi
    exec runuser -u "$OWNER" -- bash "$0"
fi

cd "$REPO"
exec >>muse_handoff/returns/drive_pull.log 2>&1
exec 9>muse_handoff/returns/.drive_pull.lock
flock -n 9 || { echo "$(date -u +%FT%TZ) previous pull still running"; exit 0; }
echo "== $(date -u +%FT%TZ)"

DRIVE="${CHURCHMAP_DRIVE:-/mnt/g/My Drive/churchmap-handoff}"
[[ -d $DRIVE ]] || { echo "Drive folder not available: $DRIVE"; exit 0; }

# 9>&-: the server outlives this script and must not inherit the lock's descriptor,
# or it holds the lock and every later pull reports "previous pull still running".
pg_isready -h localhost -p 5433 -q || /usr/lib/postgresql/14/bin/pg_ctl -D analytics/.pgdata \
    -o "-p 5433 -k $REPO/analytics/.pgdata -c listen_addresses=localhost" -l analytics/.pgdata/server.log start 9>&-
for _ in $(seq 60); do pg_isready -h localhost -p 5433 -q && break; sleep 1; done

python3 muse_handoff/drive_sync.py pull
echo "exit=$?"
