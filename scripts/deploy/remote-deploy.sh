#!/usr/bin/env bash

set -euo pipefail

APP_DIR="${1:?APP_DIR is required}"
DEPLOY_BRANCH="${2:?DEPLOY_BRANCH is required}"
SOURCE_SHA="${3:?SOURCE_SHA is required}"
IMAGE_NAME="${4:?IMAGE_NAME is required}"
IMAGE_TAG="${5:?IMAGE_TAG is required}"
DEFAULT_APP_PORT="${6:-8000}"
COMPOSE_FILE="${7:-docker-compose.yml}"
RUNTIME_ENV_FILE="${8:-.env.production}"
DEPLOY_TARGET="${9:-deploy}"
EXPECTED_APP_ENV="${10:-}"
COMPOSE_PROJECT_NAME_VALUE="${11:-bisakerja-scraper}"

log() {
  printf '[deploy] %s\n' "$1"
}

wait_for_health() {
  local name="$1"
  local url="$2"
  local attempts="${3:-12}"
  local sleep_seconds="${4:-5}"
  local tmp_body
  tmp_body="$(mktemp)"
  trap 'rm -f "$tmp_body"' RETURN

  for attempt in $(seq 1 "$attempts"); do
    local status_code
    status_code="$(curl --silent --show-error --output "$tmp_body" --write-out '%{http_code}' "$url" || true)"
    if [ "$status_code" = "200" ]; then
      return 0
    fi
    log "$name check attempt $attempt/$attempts failed with status $status_code"
    sleep "$sleep_seconds"
  done

  printf '%s check failed for %s after %s attempts\n' "$name" "$url" "$attempts" >&2
  printf '%s\n' "last response body:" >&2
  cat "$tmp_body" >&2 || true
  return 1
}

require_command() {
  if ! command -v "$1" >/dev/null 2>&1; then
    printf 'Missing required command: %s\n' "$1" >&2
    exit 1
  fi
}

require_file() {
  if [ ! -f "$1" ]; then
    printf 'Missing required file: %s\n' "$1" >&2
    exit 1
  fi
}

env_value() {
  awk -F= -v key="$1" '
    $1 == key {
      value = substr($0, length($1) + 2)
      gsub(/^[[:space:]]+|[[:space:]]+$/, "", value)
      gsub(/^"|"$/, "", value)
      print value
      exit
    }
  ' "$RUNTIME_ENV_FILE"
}

require_command git
require_command docker
require_command curl

cd "$APP_DIR"

if ! git rev-parse --is-inside-work-tree >/dev/null 2>&1; then
  printf 'Target directory is not a git repository: %s\n' "$APP_DIR" >&2
  exit 1
fi

require_file "$RUNTIME_ENV_FILE"
require_file "$COMPOSE_FILE"

chmod 600 "$RUNTIME_ENV_FILE"

declared_app_env="$(env_value APP_ENV)"
declared_port="$(env_value PORT)"
declared_app_port="$(env_value APP_PORT)"

if [ -z "$declared_app_env" ]; then
  printf 'APP_ENV is missing in %s\n' "$RUNTIME_ENV_FILE" >&2
  exit 1
fi

if [ -n "$EXPECTED_APP_ENV" ] && [ "$declared_app_env" != "$EXPECTED_APP_ENV" ]; then
  printf \
    'APP_ENV mismatch for %s deploy: expected %s but found %s in %s\n' \
    "$DEPLOY_TARGET" \
    "$EXPECTED_APP_ENV" \
    "$declared_app_env" \
    "$RUNTIME_ENV_FILE" >&2
  exit 1
fi

log "Syncing repository branch $DEPLOY_BRANCH"
git fetch origin "$DEPLOY_BRANCH" --prune

if ! git diff --quiet || ! git diff --cached --quiet; then
  printf 'Target repository has local changes; refusing to reset deploy checkout.\n' >&2
  git status --short >&2
  exit 1
fi

if ! git merge-base --is-ancestor "$SOURCE_SHA" "origin/$DEPLOY_BRANCH"; then
  printf \
    'Source SHA %s is not contained in origin/%s; refusing deploy.\n' \
    "$SOURCE_SHA" \
    "$DEPLOY_BRANCH" >&2
  exit 1
fi

current_branch="$(git rev-parse --abbrev-ref HEAD)"
if [ "$current_branch" != "$DEPLOY_BRANCH" ]; then
  git checkout -B "$DEPLOY_BRANCH" "origin/$DEPLOY_BRANCH"
fi

git reset --hard "$SOURCE_SHA"

export APP_IMAGE="${IMAGE_NAME}:${IMAGE_TAG}"
export PORT="${declared_port:-$DEFAULT_APP_PORT}"
export APP_PORT="${declared_app_port:-$PORT}"
export RUNTIME_ENV_FILE
export COMPOSE_PROJECT_NAME="$COMPOSE_PROJECT_NAME_VALUE"

log "Pulling immutable application image $APP_IMAGE"
docker compose -f "$COMPOSE_FILE" --env-file "$RUNTIME_ENV_FILE" pull app scheduler

log "Running database connectivity preflight"
docker compose -f "$COMPOSE_FILE" --env-file "$RUNTIME_ENV_FILE" run --rm --no-deps app \
  python scripts/deploy/db_preflight.py --from-env

log "Applying Alembic migrations"
docker compose -f "$COMPOSE_FILE" --env-file "$RUNTIME_ENV_FILE" run --rm --no-deps app alembic upgrade head

log "Starting application and scheduler services"
docker compose -f "$COMPOSE_FILE" --env-file "$RUNTIME_ENV_FILE" up -d --wait app scheduler

log "Running health checks"
wait_for_health "liveness" "http://127.0.0.1:${APP_PORT}/health/live"
wait_for_health "readiness" "http://127.0.0.1:${APP_PORT}/health/ready"

log "Container status"
docker compose -f "$COMPOSE_FILE" --env-file "$RUNTIME_ENV_FILE" ps

log "Deployment completed successfully for $DEPLOY_TARGET"
