#!/usr/bin/env bash
# Hourly Drive pull, started by Windows Task Scheduler (task "ChurchMapMusePull"):
#
#   conhost.exe --headless wsl.exe -d Ubuntu -u root -- bash <repo>/muse_handoff/drive_pull_hourly.sh
#
# As root it only mounts Google Drive for desktop (F:) if WSL lost the mount, then
# re-runs itself as the repo owner. Output goes to muse_handoff/returns/drive_pull.log.
set -uo pipefail
REPO="$(cd "$(dirname "$0")/.." && pwd)"
OWNER="$(stat -c %U "$REPO")"

if [[ $(id -u) == 0 ]]; then
    if ! mountpoint -q /mnt/f; then
        mkdir -p /mnt/f
        mount -t drvfs F: /mnt/f -o "uid=$(id -u "$OWNER"),gid=$(id -g "$OWNER")" || true
    fi
    exec runuser -u "$OWNER" -- bash "$0"
fi

cd "$REPO"
exec >>muse_handoff/returns/drive_pull.log 2>&1
exec 9>muse_handoff/returns/.drive_pull.lock
flock -n 9 || { echo "$(date -u +%FT%TZ) previous pull still running"; exit 0; }
echo "== $(date -u +%FT%TZ)"

DRIVE="${CHURCHMAP_DRIVE:-/mnt/f/My Drive/churchmap-handoff}"
[[ -d $DRIVE ]] || { echo "Drive folder not available: $DRIVE"; exit 0; }

pg_isready -h localhost -p 5433 -q || /usr/lib/postgresql/14/bin/pg_ctl -D analytics/.pgdata \
    -o "-p 5433 -k $REPO/analytics/.pgdata -c listen_addresses=localhost" -l analytics/.pgdata/server.log start
for _ in $(seq 60); do pg_isready -h localhost -p 5433 -q && break; sleep 1; done

python3 muse_handoff/drive_sync.py pull
echo "exit=$?"
