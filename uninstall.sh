#!/bin/sh
# Ordinary removal uses only the installed AAG OFF path, then owned-file removal.
set -eu
PROJECT_DIR=$(CDPATH='' cd -- "$(dirname -- "$0")" && pwd)
case "${1-}" in
    --root|--system) exec "$PROJECT_DIR/scripts/uninstall.sh" "$@" ;;
    *) exec "$PROJECT_DIR/scripts/uninstall.sh" --system "$@" ;;
esac
