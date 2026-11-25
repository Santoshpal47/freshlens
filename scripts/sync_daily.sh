#!/usr/bin/env bash
# Daily landing, run on an India-based machine (api.data.gov.in only answers Indian IP addresses).
#
#   1. pull the data branch (checked out at data/raw)
#   2. land today's prices from the API (gzip JSON, ~1 MB, < 30 s)
#   3. commit + push them to the data branch
#   4. in the evening run (or with --build): trigger the GitHub Actions build + deploy
#   5. refresh the local lake too, so the local dashboard stays current (non-fatal)
#
# Scheduled by scripts/install_scheduler.sh (launchd, 18:30 and 22:30 IST). Log: data/sync.log
set -euo pipefail
export PATH="$HOME/.local/bin:/opt/homebrew/bin:/usr/local/bin:/usr/bin:/bin"
cd "$(dirname "$0")/.."

log() { echo "$(date '+%F %T') $*"; }
auth=(-c credential.helper= -c "credential.helper=!gh auth git-credential")
repo=$(gh repo view --json nameWithOwner --jq .nameWithOwner)
bot=(-c user.name=freshlens-sync -c "user.email=117199886+Santoshpal47@users.noreply.github.com")

log "sync start ($repo)"
if [ ! -d data/raw/.git ]; then
  git "${auth[@]}" clone -q --branch data --single-branch "https://github.com/$repo.git" data/raw
fi
git -C data/raw "${auth[@]}" pull -q --rebase origin data

uv run freshlens daily --land-only

git -C data/raw add -A
if git -C data/raw diff --cached --quiet; then
  log "nothing new to push"
else
  git -C data/raw "${bot[@]}" commit -qm "raw: snapshot $(date '+%F %H:%M') IST"
  git -C data/raw "${auth[@]}" push -q origin HEAD:data
  log "pushed raw snapshot to the data branch"
fi

if [ "$(date +%H)" -ge 21 ] || [ "${1:-}" = "--build" ]; then
  gh workflow run daily.yml -R "$repo" && log "triggered GitHub build + deploy"
fi

if [ "${FRESHLENS_LOCAL_BUILD:-1}" = 1 ]; then
  SPARK_LOCAL_IP=127.0.0.1 uv run freshlens daily --no-fetch >> data/local_build.log 2>&1 \
    && log "local lake refreshed" || log "local build failed (non-fatal, see data/local_build.log)"
fi
log "sync done"
