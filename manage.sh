#!/bin/bash
# Start, stop, restart, or inspect one installed instance.

set -euo pipefail

ACTION="${1:-status}"
INSTANCE="${2:-main}"

case "$ACTION" in
    start|stop|restart|status) ;;
    *) echo "Usage: $0 {start|stop|restart|status} [instance]" >&2; exit 2 ;;
esac

if [ "$INSTANCE" = "main" ]; then
    services=(minecraft discord-bot minecraft-monitor)
else
    services=("minecraft-$INSTANCE" "discord-bot-$INSTANCE" "minecraft-monitor-$INSTANCE")
fi

installed=()
for service in "${services[@]}"; do
    if systemctl cat "$service" >/dev/null 2>&1; then
        installed+=("$service")
    fi
done

[ "${#installed[@]}" -gt 0 ] || {
    echo "No services found for instance: $INSTANCE" >&2
    exit 1
}

if [ "$ACTION" = "status" ]; then
    systemctl status "${installed[@]}" --no-pager
else
    sudo systemctl "$ACTION" "${installed[@]}"
fi
