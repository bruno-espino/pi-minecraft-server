#!/bin/bash
# Compatibility wrapper for the main installer.
set -e
exec "$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)/install.sh" --no-discord --install-services "$@"
