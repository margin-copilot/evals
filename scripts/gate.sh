#!/usr/bin/env bash
# Run the CI suite against one service at one commit: gate.sh <service> <sha>
set -euo pipefail

usage() { echo "usage: $0 <orchestrator|data-agent> <40-hex sha>" >&2; exit 2; }

[ $# -eq 2 ] || usage
service=$1
sha=$2
case "$service" in orchestrator | data-agent) ;; *) usage ;; esac
[[ $sha =~ ^[0-9a-f]{40}$ ]] || usage

cd "$(dirname "$0")/.."
uv sync --locked
uv pip install "$service @ git+https://github.com/margin-copilot/$service@$sha"
uv run --no-sync pytest -q -rxX
