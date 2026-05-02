#!/usr/bin/env bash

set -euo pipefail

APP_DIR="${1:?APP_DIR is required}"
DEPLOY_BRANCH="${2:?DEPLOY_BRANCH is required}"
IMAGE_NAME="${3:?IMAGE_NAME is required}"
IMAGE_TAG="${4:?IMAGE_TAG is required}"
DEFAULT_APP_PORT="${5:-8000}"
COMPOSE_FILE="${6:-docker-compose.yml}"
RUNTIME_ENV_FILE="${7:-.env.production}"
DEPLOY_TARGET="${8:-deploy}"
EXPECTED_APP_ENV="${9:-}"
COMPOSE_PROJECT_NAME_VALUE="${10:-bisakerja-scraper}"

log() {
  printf '[deploy] %s\n' "$1"
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

current_branch="$(git rev-parse --abbrev-ref HEAD)"
if [ "$current_branch" != "$DEPLOY_BRANCH" ]; then
  git checkout -B "$DEPLOY_BRANCH" "origin/$DEPLOY_BRANCH"
fi

git reset --hard "origin/$DEPLOY_BRANCH"

export APP_IMAGE="${IMAGE_NAME}:${IMAGE_TAG}"
export PORT="${declared_port:-$DEFAULT_APP_PORT}"
export APP_PORT="${declared_app_port:-$PORT}"
export COMPOSE_PROJECT_NAME="$COMPOSE_PROJECT_NAME_VALUE"

log "Pulling latest application image $APP_IMAGE"
docker compose -f "$COMPOSE_FILE" --env-file "$RUNTIME_ENV_FILE" pull app

log "Applying Alembic migrations"
docker compose -f "$COMPOSE_FILE" --env-file "$RUNTIME_ENV_FILE" run --rm --no-deps app alembic upgrade head

log "Starting application service"
docker compose -f "$COMPOSE_FILE" --env-file "$RUNTIME_ENV_FILE" up -d --wait app

log "Running health checks"
curl --fail --silent --show-error "http://127.0.0.1:${APP_PORT}/health/live" >/dev/null
curl --fail --silent --show-error "http://127.0.0.1:${APP_PORT}/health/ready" >/dev/null

log "Container status"
docker compose -f "$COMPOSE_FILE" --env-file "$RUNTIME_ENV_FILE" ps

log "Deployment completed successfully for $DEPLOY_TARGET"
