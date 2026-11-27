#!/usr/bin/env bash
# Run the CI suite against one service at one commit: gate.sh <service> <sha>
set -euo pipefail

usage() { echo "usage: $0 <orchestrator|data-agent> <40-hex sha>" >&2; exit 2; }

[ $# -eq 2 ] || usage
service=$1
sha=$2
case "$service" in orchestrator | data-agent) ;; *) usage ;; esac
[[ $sha =~ ^[0-9a-f]{40}$ ]] || usage
# Actions sets GITHUB_REPOSITORY_OWNER to the caller's org; a local run defaults to margin-copilot
org=${GITHUB_REPOSITORY_OWNER:-margin-copilot}
[[ $org =~ ^[A-Za-z0-9-]+$ ]] || { echo "gate: bad GitHub owner '$org'" >&2; exit 2; }

cd "$(dirname "$0")/.."
uv sync --locked
uv pip install "$service @ git+https://github.com/$org/$service@$sha"
got=$(uv run --no-sync python -c "import importlib.metadata as m, json, sys; print(json.loads(m.distribution(sys.argv[1]).read_text('direct_url.json'))['vcs_info']['commit_id'])" "$service")
echo "gate: $service at $got"
[ "$got" = "$sha" ] || { echo "gate: installed commit is not the requested $sha" >&2; exit 1; }
uv run --no-sync pytest -q -rxX
