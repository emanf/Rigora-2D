#!/usr/bin/env bash
# Finder double-click entry point; terminal invocation forwards the same build options.
project_root="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
bash "$project_root/Build_Rigora.sh" "$@"
result=$?
if [[ "$result" -ne 0 && -t 0 && "${1:-}" != '--no-pause' ]]; then
    read -r -p 'Build failed. Press Return to close...' _ || true
fi
exit "$result"
