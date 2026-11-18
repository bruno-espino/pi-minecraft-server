#!/bin/bash
# Back up the world and server settings to backups/, keeping the newest
# BACKUP_KEEP archives. Skips the backup when nothing changed since the last one.

set -euo pipefail

DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
SERVER_DIR="$DIR/server"
BACKUP_DIR="$DIR/backups"
value() { [ ! -f "$2" ] || sed -n "s/^$1=//p" "$2" | tail -1; }
KEEP="$(value BACKUP_KEEP "$DIR/.env")"
KEEP="${KEEP:-7}"
rcon() { "$DIR/.venv/bin/python" -m minecraft_manager rcon "$@" >/dev/null; }

LEVEL="$(value level-name "$SERVER_DIR/server.properties")"
LEVEL="${LEVEL:-world}"
[ -f "$SERVER_DIR/$LEVEL/level.dat" ] || { echo "No world to back up yet"; exit 0; }

mkdir -p "$BACKUP_DIR"
exec 9>"$BACKUP_DIR/.lock"
flock -n 9 || { echo "Another backup is running" >&2; exit 1; }

worlds=()
for world in "$LEVEL" "${LEVEL}_nether" "${LEVEL}_the_end"; do
    [ ! -d "$SERVER_DIR/$world" ] || worlds+=("$world")
done

# Archive names are timestamps, so glob order is oldest to newest.
shopt -s nullglob
archives=("$BACKUP_DIR"/world-*.tar.gz)
latest=""
(( ${#archives[@]} == 0 )) || latest="${archives[${#archives[@]}-1]}"
if [ -n "$latest" ] && [ -z "$(cd "$SERVER_DIR" && find "${worlds[@]}" -newer "$latest" -print -quit)" ]; then
    echo "World unchanged since $(basename "$latest"); nothing to do"
    exit 0
fi

archive="$BACKUP_DIR/world-$(date +%Y%m%d-%H%M%S).tar.gz"
saving_off=false
cleanup() {
    rm -f "$archive.part"
    [ "$saving_off" = false ] || rcon save-on || echo "WARNING: could not re-enable saving" >&2
}
trap cleanup EXIT

if systemctl is-active --quiet minecraft; then
    rcon save-off
    saving_off=true
    rcon save-all flush
fi

items=("${worlds[@]}")
for item in server.properties ops.json whitelist.json banned-players.json banned-ips.json config plugins mods; do
    [ ! -e "$SERVER_DIR/$item" ] || items+=("$item")
done
tar -C "$SERVER_DIR" --exclude='*.jar' -czf "$archive.part" -- "${items[@]}"

if [ "$saving_off" = true ]; then
    rcon save-on
    saving_off=false
fi
tar -tzf "$archive.part" "$LEVEL/level.dat" >/dev/null 2>&1 || { echo "Backup is missing level.dat" >&2; exit 1; }
mv "$archive.part" "$archive"
chmod 600 "$archive"
echo "Backed up to backups/$(basename "$archive") ($(du -h "$archive" | cut -f1))"

archives=("$BACKUP_DIR"/world-*.tar.gz)
excess=$(( ${#archives[@]} - KEEP ))
(( excess > 0 )) || exit 0
for old in "${archives[@]:0:excess}"; do
    rm -f "$old"
    echo "Removed old backup $(basename "$old")"
done
