#!/usr/bin/env bash
set -euo pipefail

discover=false
if [[ ${1:-} == --discover ]]; then
  discover=true
  shift
fi
watch_minutes=${1:-0}
if [[ ! "$watch_minutes" =~ ^(0|[1-9][0-9]{0,2})$ ]] || ((watch_minutes > 345)); then
  echo 'Expected a watch window in minutes between 0 and 345.' >&2
  exit 2
fi

state="${RUNNER_TEMP:?}/keirin-public-results"
ref=refs/heads/state/keirin-public-results
deadline=$((SECONDS + watch_minutes * 60))

while true; do
  next_poll=$((SECONDS + 900))
  git fetch --no-tags --depth=1 origin "$ref"
  state_sha=$(git rev-parse --verify FETCH_HEAD)
  if [[ -f "$state/.git" ]]; then
    git -C "$state" switch --detach "$state_sha"
  else
    git worktree add --detach "$state" "$state_sha"
  fi

  discovery_status=0
  if [[ "$discover" == true ]]; then
    python -m scripts.keirin_public_site_rosters --state-directory "$state" \
      | tee -a "${GITHUB_STEP_SUMMARY:?}" || discovery_status=$?
  fi
  # A missing forecast or an unavailable Site must not block today's registered races.
  status=0
  python -m scripts.keirin_public_site_results --state-directory "$state" --stop-when-complete \
    | tee -a "${GITHUB_STEP_SUMMARY:?}" || status=$?
  # 10 means no races are outstanding. 75 means preserve the collected rows and stop on a source failure.
  if ((status != 0 && status != 10 && status != 75)); then
    exit "$status"
  fi

  git -C "$state" add -- rosters results
  if ! git -C "$state" diff --cached --quiet; then
    git -C "$state" -c user.name='github-actions[bot]' \
      -c user.email='41898282+github-actions[bot]@users.noreply.github.com' \
      commit -m 'Update public keirin result observations'
    git -C "$state" push origin "HEAD:$ref"
  fi

  if ((status == 75)); then
    exit "$status"
  fi
  if ((discovery_status != 0)); then
    exit "$discovery_status"
  fi
  now=$SECONDS
  if ((status == 10 || watch_minutes == 0 || now >= deadline)); then
    break
  fi
  if ((next_poll >= deadline)); then
    sleep "$((deadline - now))"
    break
  fi
  if ((next_poll > now)); then
    sleep "$((next_poll - now))"
  fi
  if ((SECONDS >= deadline)); then
    break
  fi
done
