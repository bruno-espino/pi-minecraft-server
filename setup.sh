#!/bin/bash
# Compatibility wrapper for a Minecraft-only installation.
set -e
exec "$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)/install.sh" --no-discord "$@"
