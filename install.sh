#!/bin/sh
# Default is explicit system installation. No network activation or autostart.
set -eu
PROJECT_DIR=$(CDPATH='' cd -- "$(dirname -- "$0")" && pwd)
case "${1-}" in
    --root|--system) exec "$PROJECT_DIR/scripts/install.sh" "$@" ;;
    *) exec "$PROJECT_DIR/scripts/install.sh" --system "$@" ;;
esac
