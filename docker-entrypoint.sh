#!/usr/bin/env bash
set -euo pipefail

SOURCE="${INTEL_SOURCE:?INTEL_SOURCE must be set to twcert or cisa_kev}"

if [ -z "${SINCE:-}" ]; then
  if [ "$SOURCE" = "twcert" ]; then
    SINCE="$(TZ=Asia/Taipei date -d yesterday +%F)"
  else
    SINCE="$(date -u -d yesterday +%F)"
  fi
fi

exec uv run python main.py --source "$SOURCE" --since "$SINCE" "$@"
