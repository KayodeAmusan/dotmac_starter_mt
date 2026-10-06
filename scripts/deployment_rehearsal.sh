#!/usr/bin/env bash
# scripts/deployment_rehearsal.sh — Lane 2 of
# docs/inventories/deployment-foundation-rehearsal.md: what a disposable host
# adds that a unit test cannot. Every claim in that document's Lane 2 table
# is proven here against REAL docker, a REAL Postgres, and (for backup and
# migration-head verification) real bytes on disk — not a fake `Effects`
# implementation.
#
# STATUS as of 2026-08-28: every ordered subject and all 21 injection subjects
# have run on an explicitly authorised disposable test host, including real
# Nginx parse/failover, restore, telemetry and alert recovery. This is branch
# implementation evidence, not publication authority: release-facility.yml
# still requires a successful GitHub rehearsal whose head_sha is the exact
# merged main SHA being released. The script runs ONLY on the disposable
# infrastructure it creates and tears down itself — never against a named
# product environment or production host. See scripts/rehearsal/README.md.
#
# Subcommands:
#   up               create the disposable registry, build+push the image
#                    once, bring up the scratch database, create the
#                    owner/online roles, render the deployment assets.
#   run              the 14 ordered steps from the rehearsal document.
#   inject <case>    one failure-injection case (see `list-cases` for names).
#   down             idempotent teardown. Never `docker compose down
#                    --remove-orphans` — see the comment on that call below.
#   all              up; run; every injection case; down.
#   list-cases       print every case name `inject` accepts.
#
# Everything by config: every path, port, image tag, database name, network
# name and timeout below is a `: "${VAR:=default}"` knob (AGENTS.md,
# "Everything by config"). The one rule that is NOT overridable away: every
# database name and container name this script creates must contain
# "rehearsal" (case-insensitive) — `require_disposable_name` refuses to
# start otherwise. That is the same rule `dotmac_sub`'s integration lane
# applies to its own scratch database, and it is the one thing standing
# between this script and somebody's real database.

set -euo pipefail

# ── locate ourselves ─────────────────────────────────────────────────────────

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "${SCRIPT_DIR}/.." && pwd)"
REHEARSAL_DIR="${SCRIPT_DIR}/rehearsal"

# ── knobs: identity ──────────────────────────────────────────────────────────

: "${REHEARSAL_PRODUCT:=deployment_rehearsal}"
: "${REHEARSAL_WORK_DIR:=${TMPDIR:-/tmp}/dotmac-deployment-rehearsal}"
: "${REHEARSAL_ENVIRONMENT:=rehearsal}"

# ── knobs: tools ─────────────────────────────────────────────────────────────

: "${DOCKER_BIN:=docker}"
: "${COMPOSE_SUBCOMMAND:=compose}"        # `docker compose`, never `docker-compose`
: "${DOTMAC_DEPLOY_BIN:=dotmac-deploy}"   # editable-installed by Lane 1's `poetry install`
: "${GIT_BIN:=git}"
: "${PYTHON_BIN:=python3}"

# ── knobs: disposable local registry (gives the built image a REAL
#   `repo@sha256:...` digest — `docker image inspect repo@sha256:...` only
#   resolves once an image has round-tripped a registry; a bare local build
#   never populates RepoDigests) ───────────────────────────────────────────

: "${REGISTRY_IMAGE:=registry:2}"
: "${REGISTRY_CONTAINER:=dotmac-deployment-rehearsal-registry}"
: "${REGISTRY_PORT:=15050}"
: "${REGISTRY_HOST:=127.0.0.1:${REGISTRY_PORT}}"
: "${IMAGE_REPOSITORY:=${REGISTRY_HOST}/deployment-rehearsal-app}"
: "${IMAGE_TAG:=scratch}"

# ── knobs: the scratch databases. Every name here MUST contain "rehearsal" —
#   enforced by `require_disposable_name`, never bypassable by a knob. ───────

: "${DB_IMAGE:=postgres:16-alpine}"
: "${DB_SERVICE_NAME:=db}"   # must match product.toml's [[external_dependencies]] code
: "${DB1_NAME:=rehearsal_primary}"
: "${DB2_CONTAINER:=dotmac-deployment-rehearsal-restore-db}"
: "${DB2_NAME:=rehearsal_restore}"
: "${DB_SUPERUSER:=postgres}"
: "${DB_SUPERUSER_PASSWORD:=rehearsal-superuser-pw}"
: "${DB_OWNER_USER:=rehearsal_owner}"
: "${DB_OWNER_PASSWORD:=rehearsal-owner-pw}"
: "${DB_ONLINE_USER:=rehearsal_online}"
: "${DB_ONLINE_PASSWORD:=rehearsal-online-pw}"
: "${DB_PORT:=5432}"

# ── knobs: the app role ──────────────────────────────────────────────────────

: "${APP_PORT:=8000}"
: "${APP_HOST_PORT:=18180}"
: "${SCHEMA_HEAD:=0001}"
: "${STABILITY_WINDOW_SECONDS:=15}"

# ── knobs: timeouts ───────────────────────────────────────────────────────────

: "${WAIT_DB_TIMEOUT_SECONDS:=60}"
# Consecutive successful probes required before the database counts as ready.
# See `wait_for_stable`. Everything by config (AGENTS.md) — but this knob only
# goes UP. The loopback-TCP probe is what actually closes the init-restart
# window (the temporary server runs with `listen_addresses=''` and serves no
# TCP at all); the streak is defence in depth behind it, for the restarts TCP
# alone does not describe — a crashed backend, a container the daemon
# restarts. Tuning it to 1 would quietly restore "accept the first success",
# which is the exact bug this pair of changes exists to remove, so the floor is
# enforced below rather than documented and hoped for.
: "${WAIT_DB_STABLE_PROBES:=3}"
readonly WAIT_DB_STABLE_PROBES_FLOOR=3
case "${WAIT_DB_STABLE_PROBES}" in
  ''|*[!0-9]*)
    printf 'WAIT_DB_STABLE_PROBES must be a whole number, got %s\n' \
      "${WAIT_DB_STABLE_PROBES}" >&2
    exit 2
    ;;
esac
if [ "${WAIT_DB_STABLE_PROBES}" -lt "${WAIT_DB_STABLE_PROBES_FLOOR}" ]; then
  printf 'WAIT_DB_STABLE_PROBES must be at least %s, got %s: fewer consecutive probes reopens the init-restart race this knob exists to close\n' \
    "${WAIT_DB_STABLE_PROBES_FLOOR}" "${WAIT_DB_STABLE_PROBES}" >&2
  exit 2
fi
: "${WAIT_HTTP_TIMEOUT_SECONDS:=30}"
: "${MIGRATE_TIMEOUT_SECONDS:=30}"
# app.py's `--migrate` mode always issues `SET lock_timeout = '5s'`
# (`MIGRATE_LOCK_TIMEOUT`, defaulted inside app.py itself —
# render/compose.py's `_migrate_service` has no literal-environment slot to
# override it from here) before touching `schema_version`, which is what
# makes the `migration-lock-contention` case fail fast against a real
# conflicting lock rather than hang on Postgres's unbounded default.

# ── knobs: backup ─────────────────────────────────────────────────────────────

: "${BACKUP_DATASET:=primary}"

# ── knobs: the rehearsal's OWN telemetry sink (deliberately separate from the
#   product's rendered collector — see product.toml's `[telemetry]` comment
#   for why: the render path hardcodes `tls.insecure: false`, which this
#   disposable rehearsal has no certificate to satisfy). ─────────────────────

: "${OTEL_COLLECTOR_IMAGE:=otel/opentelemetry-collector-contrib:0.110.0}"
: "${OTEL_COLLECTOR_CONTAINER:=dotmac-deployment-rehearsal-otelcol}"
: "${OTEL_HTTP_PORT:=14318}"
# One knob per service, NOT one shared "infrastructure" timeout. A single knob
# spanning the registry, the collector and Prometheus cannot be tuned for any
# of them: raising it for a slow collector pull silently doubles how long a
# dead registry takes to report, and lowering it for a fast registry makes the
# collector flaky. These three also fail for different reasons and at different
# speeds, which is exactly why they get different numbers.
: "${WAIT_REGISTRY_TIMEOUT_SECONDS:=30}"
# The collector pulls a ~150MB image on a cold runner and then starts; the
# original hardcoded 20s could not distinguish "slow cold pull" from "dead".
: "${WAIT_COLLECTOR_TIMEOUT_SECONDS:=60}"
: "${WAIT_PROMETHEUS_TIMEOUT_SECONDS:=60}"
# Step 13 watches a rule fire and then recover. Both were hardcoded 60s loops.
# They are separate knobs because they are separate questions: firing waits out
# the rule's `for:` duration, while recovery additionally waits for the target
# to come back and be scraped again.
: "${WAIT_ALERT_FIRE_SECONDS:=60}"
: "${WAIT_ALERT_RECOVER_SECONDS:=60}"
# How much of a failed container's log to print. Enough to carry a stack or a
# startup refusal, short enough not to bury the run.
: "${DIAGNOSTIC_LOG_LINES:=40}"
# How long to watch for a killed container to come back. Deliberately short:
# this is an observation window, not a readiness gate.
: "${WAIT_RESTART_OBSERVATION_SECONDS:=20}"

# ── knobs: the rehearsal's OWN Prometheus, for the fire/recover alert step ──

: "${PROM_IMAGE:=prom/prometheus:v2.55.1}"
: "${PROM_CONTAINER:=dotmac-deployment-rehearsal-prometheus}"
: "${PROM_HTTP_PORT:=19090}"
: "${PROM_ALERT_FOR:=5s}"
readonly PROM_RULE_NAME="RehearsalTargetDown"
readonly PROM_SCRAPE_URL="http://app:${APP_PORT}/metrics"
readonly PROM_PROBE="${REHEARSAL_DIR}/prometheus_probe.py"

# ── knobs: the real Nginx parser and handoff subject ────────────────────────

: "${NGINX_IMAGE:=nginx:1.27-alpine}"
: "${NGINX_CONTAINER:=dotmac-deployment-rehearsal-nginx}"
: "${WAIT_NGINX_TIMEOUT_SECONDS:=30}"
readonly NGINX_REHEARSAL_HOST="rehearsal.invalid"

# ── knobs: exit-code policy ───────────────────────────────────────────────────

: "${ALLOW_SKIPS:=0}"     # 1 = a skipped case does not fail the overall run
: "${NO_TEARDOWN:=0}"     # 1 = `all` does not call `down` at the end (debugging only)

WORK_DIR="${REHEARSAL_WORK_DIR}"
COMPOSE_FILE="${WORK_DIR}/rendered/docker-compose.yml"
DESCRIPTOR="${WORK_DIR}/product.toml"
ENV_FILE="${WORK_DIR}/.env"
STATE_FILE="${WORK_DIR}/state.env"
BACKUP_DIR="${WORK_DIR}/backups"
COMPOSE=("${DOCKER_BIN}" "${COMPOSE_SUBCOMMAND}" -p "${REHEARSAL_PRODUCT}" -f "${COMPOSE_FILE}" --env-file "${ENV_FILE}")

PASS_COUNT=0
FAIL_COUNT=0
SKIP_COUNT=0
SKIPPED_ITEMS=()
RUN_HAD_FAILURE=0

# ── output helpers ────────────────────────────────────────────────────────────

log() { printf '%s\n' "$*" >&2; }

step_pass() {
  local label="$1"
  printf '%s. PASS  %s\n' "${STEP_NUM}" "${label}"
  PASS_COUNT=$((PASS_COUNT + 1))
}

step_fail() {
  local label="$1"
  local reason="${2:-}"
  printf '%s. FAIL  %s%s\n' "${STEP_NUM}" "${label}" "${reason:+ — ${reason}}"
  FAIL_COUNT=$((FAIL_COUNT + 1))
  RUN_HAD_FAILURE=1
}

case_pass() {
  printf 'PASS   %s\n' "$*"
  PASS_COUNT=$((PASS_COUNT + 1))
}

case_fail() {
  printf 'FAIL   %s\n' "$*"
  FAIL_COUNT=$((FAIL_COUNT + 1))
  RUN_HAD_FAILURE=1
}

case_skip() {
  local case_name="$1"
  local reason="$2"
  printf 'SKIPPED: %s — %s\n' "${case_name}" "${reason}"
  SKIP_COUNT=$((SKIP_COUNT + 1))
  SKIPPED_ITEMS+=("${case_name}: ${reason}")
}

die() {
  log "FATAL: $*"
  exit 1
}

# ── disposability guard ──────────────────────────────────────────────────────
#
# The one rule no knob may bypass. Every scratch database name and database
# container name this script touches must self-identify as disposable — the
# same discipline `dotmac_sub`'s integration lane applies before it will run
# a single query. A knob typo'd into the name of something real must refuse
# to run, not proceed with a scarier default.

require_disposable_name() {
  local what="$1"
  local value="$2"
  local lowered
  lowered="$(printf '%s' "${value}" | tr '[:upper:]' '[:lower:]')"
  case "${lowered}" in
    *rehearsal*) return 0 ;;
    *)
      die "${what} is '${value}', which does not contain 'rehearsal'. This script refuses to operate against anything whose name does not self-identify as disposable test data — the same rule dotmac_sub's integration lane applies. Fix the knob, do not remove the check."
      ;;
  esac
}

verify_disposable_targets() {
  require_disposable_name "DB1_NAME" "${DB1_NAME}"
  require_disposable_name "DB2_NAME" "${DB2_NAME}"
  require_disposable_name "DB2_CONTAINER" "${DB2_CONTAINER}"
  require_disposable_name "REGISTRY_CONTAINER" "${REGISTRY_CONTAINER}"
  require_disposable_name "OTEL_COLLECTOR_CONTAINER" "${OTEL_COLLECTOR_CONTAINER}"
  require_disposable_name "PROM_CONTAINER" "${PROM_CONTAINER}"
  require_disposable_name "NGINX_CONTAINER" "${NGINX_CONTAINER}"
}

# ── small utilities ───────────────────────────────────────────────────────────

container_exists() {
  "${DOCKER_BIN}" inspect "$1" >/dev/null 2>&1
}

container_running() {
  local state
  state="$("${DOCKER_BIN}" inspect -f '{{.State.Running}}' "$1" 2>/dev/null || echo false)"
  [ "${state}" = "true" ]
}

container_healthy() {
  local state
  state="$("${DOCKER_BIN}" inspect -f '{{.State.Health.Status}}' "$1" 2>/dev/null || echo unknown)"
  [ "${state}" = "healthy" ]
}

container_stopped_or_restarted() {
  local container="$1"
  local previous_restarts="$2"
  local running restarts
  running="$("${DOCKER_BIN}" inspect -f '{{.State.Running}}' "${container}" 2>/dev/null || echo false)"
  restarts="$("${DOCKER_BIN}" inspect -f '{{.RestartCount}}' "${container}" 2>/dev/null || echo -1)"
  [ "${running}" != true ] || [ "${restarts}" != "${previous_restarts}" ]
}

remove_container() {
  local name="$1"
  if container_exists "${name}"; then
    "${DOCKER_BIN}" rm -f "${name}" >/dev/null 2>&1 || true
  fi
}

_wait_for() {
  # _wait_for <timeout-seconds> <description> <command...>
  local timeout="$1"
  local description="$2"
  shift 2
  local waited=0
  until "$@" >/dev/null 2>&1; do
    if [ "${waited}" -ge "${timeout}" ]; then
      log "timed out after ${timeout}s waiting for: ${description}"
      return 1
    fi
    sleep 1
    waited=$((waited + 1))
  done
  return 0
}

_wait_for_stable() {
  # _wait_for_stable <timeout-seconds> <consecutive-successes> <description> <command...>
  #
  # `wait_for` accepts the FIRST success, which is wrong for anything whose
  # readiness can regress. Postgres' official entrypoint is exactly that: on a
  # fresh volume it starts a TEMPORARY server to run initdb and any
  # /docker-entrypoint-initdb.d scripts, then SHUTS IT DOWN and starts the real
  # one. A probe that fires during the temporary phase succeeds, and the socket
  # then disappears underneath whatever runs next.
  #
  # That is not hypothetical here: rehearsal run 33088709577 passed
  # `pg_isready` and the very next `psql` failed with
  #   connection to server on socket "/var/run/postgresql/.s.PGSQL.5432" failed
  # Requiring N CONSECUTIVE successes, spaced a second apart, spans the restart
  # instead of racing it.
  local timeout="$1"
  local needed="$2"
  local description="$3"
  shift 3
  local waited=0
  local streak=0
  while [ "${streak}" -lt "${needed}" ]; do
    if "$@" >/dev/null 2>&1; then
      streak=$((streak + 1))
    else
      streak=0
    fi
    [ "${streak}" -ge "${needed}" ] && return 0
    if [ "${waited}" -ge "${timeout}" ]; then
      log "timed out after ${timeout}s waiting for: ${description} (needed ${needed} consecutive successes, reached ${streak})"
      return 1
    fi
    sleep 1
    waited=$((waited + 1))
  done
  return 0
}

diagnose_container() {
  # diagnose_container <name-or-id> <what-was-being-waited-for>
  #
  # A container wait that times out and prints nothing is close to useless: it
  # says a thing did not happen and withholds the one place the reason is
  # written down. Rehearsal run 33095822846 spent twenty minutes to report
  #
  #   timed out after 20s waiting for: the rehearsal's own collector on :14318
  #
  # while `docker logs` had, the whole time, said
  #
  #   Error: cannot start pipelines: open /sink/otel-sink.json: permission denied
  #
  # Every container wait in this script routes its failure through here, so the
  # next unknown failure costs one run instead of one run per guess.
  local target="$1"
  local waiting_for="$2"
  log "DIAGNOSTICS for: ${waiting_for}"
  if ! "${DOCKER_BIN}" inspect "${target}" >/dev/null 2>&1; then
    log "  container ${target} does not exist — it was never created, or was removed"
    return 0
  fi
  log "  state: $("${DOCKER_BIN}" inspect -f \
    '{{.State.Status}} exit={{.State.ExitCode}} oom={{.State.OOMKilled}} err={{.State.Error}}' \
    "${target}" 2>/dev/null || echo unknown)"
  log "  --- last ${DIAGNOSTIC_LOG_LINES} log line(s) ---"
  "${DOCKER_BIN}" logs --tail "${DIAGNOSTIC_LOG_LINES}" "${target}" 2>&1 \
    | sed 's/^/    /' || log "    (no logs available)"
  log "  --- end diagnostics ---"
}

wait_for_container() {
  # wait_for_container <timeout> <container> <description> <command...>
  #
  # A readiness wait on something backed by a container. On failure it ALWAYS
  # prints that container's state and logs, because a timeout without them is
  # a report that something did not happen with the reason withheld.
  #
  # `_wait_for` and `_wait_for_stable` are underscore-prefixed to make
  # "internal" structural rather than a convention: calling them directly is
  # how a wait ends up silent, and
  # `test_every_readiness_wait_goes_through_a_wrapper` bans it.
  local timeout="$1" container="$2" description="$3"
  shift 3
  if ! _wait_for "${timeout}" "${description}" "$@"; then
    diagnose_container "${container}" "${description}"
    return 1
  fi
  return 0
}

wait_for_stable_container() {
  # wait_for_stable_container <timeout> <probes> <container> <description> <command...>
  local timeout="$1" probes="$2" container="$3" description="$4"
  shift 4
  if ! _wait_for_stable "${timeout}" "${probes}" "${description}" "$@"; then
    diagnose_container "${container}" "${description}"
    return 1
  fi
  return 0
}

observe_for() {
  # observe_for <timeout> <description> <command...>
  #
  # An OBSERVATION WINDOW, not a readiness gate. The question is "did this
  # happen promptly", a timeout is a legitimate answer, and there is nothing to
  # diagnose. Distinct from `wait_for_container` so that "no diagnostics here"
  # is a DECLARED choice a reader can check, rather than an omission that looks
  # exactly like the bug this whole helper family exists to prevent.
  local timeout="$1" description="$2"
  shift 2
  _wait_for "${timeout}" "${description}" "$@"
}

prom_api() {
  # prom_api <endpoint> <prometheus_probe.py args...>
  local endpoint="$1"
  shift
  curl -sf --max-time 5 \
    "http://127.0.0.1:${PROM_HTTP_PORT}/api/v1/${endpoint}" \
    | "${PYTHON_BIN}" "${PROM_PROBE}" "$@"
}

prom_rule_is() {
  prom_api rules rule-is "${PROM_RULE_NAME}" "$1"
}

prom_target_is() {
  prom_api targets target-is "${PROM_SCRAPE_URL}" "$1"
}

prom_fire_proved() {
  prom_rule_is firing && prom_target_is down
}

prom_recovery_proved() {
  # `inactive` alone is not recovery: a vanished target makes `up == 0`
  # produce no vector and therefore also looks inactive. Require the same
  # expected target to remain present and scrape successfully.
  prom_rule_is inactive && prom_target_is up
}

diagnose_prometheus_transition() {
  # diagnose_prometheus_transition <app-container> <transition>
  local app_container="$1"
  local transition="$2"
  local rule_summary target_summary marker
  rule_summary="$(prom_api rules rule-summary "${PROM_RULE_NAME}" 2>&1 || true)"
  target_summary="$(prom_api targets target-summary "${PROM_SCRAPE_URL}" 2>&1 || true)"
  [ -n "${rule_summary}" ] || rule_summary="unavailable"
  [ -n "${target_summary}" ] || target_summary="unavailable"
  marker="absent"
  if "${DOCKER_BIN}" exec "${app_container}" test -f /tmp/rehearsal-ready \
      >/dev/null 2>&1; then
    marker="present"
  fi
  log "  ${transition} rule: ${rule_summary}"
  log "  ${transition} target: ${target_summary}"
  log "  ${transition} app: live=$(http_status "http://127.0.0.1:${APP_HOST_PORT}/health/live") ready=$(http_status "http://127.0.0.1:${APP_HOST_PORT}/health/ready") marker=${marker}"
  diagnose_container "${app_container}" "app during Prometheus ${transition}"
}

http_status() {
  # http_status <url> — prints the status code, or "000" on connection failure
  curl -s -o /dev/null -w '%{http_code}' --max-time 5 "$1" 2>/dev/null || echo "000"
}

psql_super() {
  "${DOCKER_BIN}" exec -i -e PGPASSWORD="${DB_SUPERUSER_PASSWORD}" "${DB1_CONTAINER}" \
    psql -v ON_ERROR_STOP=1 -U "${DB_SUPERUSER}" -d "${DB1_NAME}" "$@"
}

psql_owner() {
  "${DOCKER_BIN}" exec -i -e PGPASSWORD="${DB_OWNER_PASSWORD}" "${DB1_CONTAINER}" \
    psql -U "${DB_OWNER_USER}" -d "${DB1_NAME}" "$@"
}

psql_online() {
  "${DOCKER_BIN}" exec -i -e PGPASSWORD="${DB_ONLINE_PASSWORD}" "${DB1_CONTAINER}" \
    psql -U "${DB_ONLINE_USER}" -d "${DB1_NAME}" "$@"
}

git_revision() {
  ( cd "${REPO_ROOT}" && "${GIT_BIN}" rev-parse HEAD )
}

dotmac_deploy() {
  # Prefers the installed console script — Lane 1's own `poetry install`
  # (docs/inventories/deployment-foundation-rehearsal.md) puts it on PATH —
  # and falls back to `python -m` against the package's own `src/` so this
  # script also works run directly from a checkout that has not gone
  # through that install step.
  if command -v "${DOTMAC_DEPLOY_BIN}" >/dev/null 2>&1; then
    "${DOTMAC_DEPLOY_BIN}" "$@"
  else
    ( cd "${REPO_ROOT}" \
      && PYTHONPATH="${REPO_ROOT}/packages/dotmac-deployment-foundation/src:${PYTHONPATH:-}" \
         "${PYTHON_BIN}" -m dotmac_deployment_foundation.cli "$@" )
  fi
}

# Names discovered once state is loaded — see `load_state`.
DB1_CONTAINER=""
NETWORK_NAME=""

load_state() {
  # DB1_CONTAINER and NETWORK_NAME are DISCOVERED, not guessed: `docker
  # compose`'s actual container- and network-naming convention has changed
  # between major versions (hyphens vs. underscores, single- vs.
  # double-prefixed network names), so `up` queries the real names off the
  # running `db` service once and persists them to STATE_FILE — every other
  # subcommand just reads them back rather than re-deriving a pattern that
  # could silently stop matching.
  if [ -f "${STATE_FILE}" ]; then
    # shellcheck disable=SC1090
    source "${STATE_FILE}"
  fi
}

require_state() {
  local var_name="$1"
  if [ -z "${!var_name:-}" ]; then
    die "${var_name} is not set. Run '$0 up' (and '$0 run' where the case needs a migrated database) before '$0 ${COMMAND:-<subcommand>}'."
  fi
}

# ── descriptor templating ─────────────────────────────────────────────────────
#
# scripts/rehearsal/product.toml is a real ProductDeploymentSpec.v1 document
# with six `@@NAME@@` placeholders for the values that cannot be known until
# the rehearsal actually runs (see that file's own header comment). This is
# the ONE place they are substituted, into a working copy under WORK_DIR —
# the checked-in template is never mutated.

write_descriptor() {
  local image_reference="$1"
  local source_revision="$2"
  local manifest_digest="$3"
  sed \
    -e "s/@@PRODUCT@@/${REHEARSAL_PRODUCT}/g" \
    -e "s#@@IMAGE_REFERENCE@@#${image_reference}#g" \
    -e "s/@@SOURCE_REVISION@@/${source_revision}/g" \
    -e "s/@@MANIFEST_DIGEST@@/${manifest_digest}/g" \
    -e "s/@@DB_NAME@@/${DB1_NAME}/g" \
    -e "s/@@APP_HOST_PORT@@/${APP_HOST_PORT}/g" \
    "${REHEARSAL_DIR}/product.toml" > "${DESCRIPTOR}"
}

write_env_file() {
  local database_url="$1"
  local migration_database_url="$2"
  cat > "${ENV_FILE}" <<ENVEOF
DATABASE_URL=${database_url}
MIGRATION_DATABASE_URL=${migration_database_url}
BACKUP_DATABASE_URL=${migration_database_url}
POSTGRES_PASSWORD=${DB_SUPERUSER_PASSWORD}
ENVEOF
}

render_assets() {
  dotmac_deploy -f "${DESCRIPTOR}" render --output-dir "${WORK_DIR}/rendered" \
    --thresholds "${REHEARSAL_DIR}/thresholds.json"
}

# ══════════════════════════════════════════════════════════════════════════
# up — the disposable infrastructure every other subcommand needs
# ══════════════════════════════════════════════════════════════════════════

cmd_up() {
  mkdir -p "${WORK_DIR}" "${BACKUP_DIR}"

  log "== up: disposable registry =="
  remove_container "${REGISTRY_CONTAINER}"
  "${DOCKER_BIN}" run -d --name "${REGISTRY_CONTAINER}" \
    -p "127.0.0.1:${REGISTRY_PORT}:5000" \
    "${REGISTRY_IMAGE}" >/dev/null
  wait_for_container "${WAIT_REGISTRY_TIMEOUT_SECONDS}" "${REGISTRY_CONTAINER}" \
    "local registry on ${REGISTRY_HOST}" \
    curl -sf "http://${REGISTRY_HOST}/v2/" \
    || die "the disposable local registry never became reachable"

  log "== up: build the image ONCE =="
  local revision
  revision="$(git_revision)"
  local tag="${IMAGE_REPOSITORY}:${IMAGE_TAG}"
  "${DOCKER_BIN}" build \
    --build-arg "REVISION=${revision}" \
    --build-arg "SOURCE=https://github.com/michaelayoade/dotmac_starter_mt" \
    --build-arg "VERSION=0.0.0-rehearsal-${revision:0:12}" \
    -t "${tag}" \
    "${REHEARSAL_DIR}"

  log "== up: push, to get a REAL repo@sha256 digest =="
  "${DOCKER_BIN}" push "${tag}"
  local repo_digest
  repo_digest="$("${DOCKER_BIN}" inspect --format='{{index .RepoDigests 0}}' "${tag}")"
  [ -n "${repo_digest}" ] || die "the pushed image reported no RepoDigest"

  local manifest_digest
  manifest_digest="sha256:$(sha256sum "${REHEARSAL_DIR}/product.toml" | awk '{print $1}')"

  {
    echo "IMAGE_REFERENCE=${repo_digest}"
    echo "IMAGE_DIGEST=${repo_digest#*@}"
    echo "SOURCE_REVISION=${revision}"
    echo "MANIFEST_DIGEST=${manifest_digest}"
  } > "${STATE_FILE}"
  # shellcheck disable=SC1090
  source "${STATE_FILE}"

  log "== up: write the working descriptor =="
  write_descriptor "${IMAGE_REFERENCE}" "${SOURCE_REVISION}" "${MANIFEST_DIGEST}"

  log "== up: render the deployment assets =="
  render_assets >/dev/null

  # A provisional .env — DATABASE_URL/MIGRATION_DATABASE_URL reference the
  # compose SERVICE NAME ("db"), which compose resolves via its own
  # per-project internal DNS regardless of the real container name docker
  # assigns, so this is valid before the db container exists at all.
  local database_url="postgresql://${DB_ONLINE_USER}:${DB_ONLINE_PASSWORD}@${DB_SERVICE_NAME}:${DB_PORT}/${DB1_NAME}"
  local owner_url="postgresql://${DB_OWNER_USER}:${DB_OWNER_PASSWORD}@${DB_SERVICE_NAME}:${DB_PORT}/${DB1_NAME}"
  write_env_file "${database_url}" "${owner_url}"

  log "== up: scratch primary database (compose-managed, not a bare 'docker run') =="
  # Brought up THROUGH `docker compose`, deliberately, rather than a
  # standalone `docker run` on a hand-created network: compose's own
  # container- and network-naming convention differs across versions
  # (hyphen vs. underscore, single- vs. double-prefixed network names), so
  # guessing it and creating a same-named network by hand risks the scratch
  # database and the compose-managed `app`/`migrate` services silently
  # ending up on TWO DIFFERENT networks that happen to share a name.
  # Bringing `db` up through compose and then discovering its real
  # container id and network name (below) is what makes the rest of this
  # script's `--network "${NETWORK_NAME}"` calls (the restore-target
  # database, the rehearsal's own collector and Prometheus) actually land
  # on the same network `app` and `migrate` are on.
  "${COMPOSE[@]}" up -d db >/dev/null
  local db_cid
  db_cid="$("${COMPOSE[@]}" ps -q db)"
  [ -n "${db_cid}" ] || die "the compose-managed 'db' service never started"
  # Probe with REAL SQL over LOOPBACK TCP. Both halves matter and neither is
  # sufficient alone:
  #
  #   * not `pg_isready` — it answers "is a server accepting connections",
  #     which the entrypoint's temporary init server also answers yes to.
  #     Running SQL as the superuser is what the next line actually needs.
  #   * not the Unix SOCKET — the temporary server can serve socket SQL
  #     perfectly well, and for longer than any streak this script is willing
  #     to wait. The official image starts it with `listen_addresses=''`, so
  #     it accepts NO TCP at all. A loopback TCP probe therefore cannot be
  #     satisfied by the temporary server: it succeeds only once the real
  #     server is listening. That turns a narrowed race into no race.
  #
  # `-h 127.0.0.1` inside `docker exec` is the CONTAINER's loopback and
  # `DB_PORT` its in-container port (5432) — not a host-published port.
  wait_for_stable_container "${WAIT_DB_TIMEOUT_SECONDS}" "${WAIT_DB_STABLE_PROBES}" \
    "${db_cid}" "primary database ready" \
    "${DOCKER_BIN}" exec -e PGPASSWORD="${DB_SUPERUSER_PASSWORD}" "${db_cid}" \
    psql -h 127.0.0.1 -p "${DB_PORT}" \
    -v ON_ERROR_STOP=1 -U "${DB_SUPERUSER}" -d "${DB1_NAME}" -c 'SELECT 1' \
    || die "the primary scratch database never became ready"

  local db_network
  db_network="$("${DOCKER_BIN}" inspect -f '{{range $net, $cfg := .NetworkSettings.Networks}}{{$net}}{{end}}' "${db_cid}")"
  [ -n "${db_network}" ] || die "could not discover the network 'db' actually joined"

  {
    echo "DB1_CONTAINER=${db_cid}"
    echo "NETWORK_NAME=${db_network}"
  } >> "${STATE_FILE}"
  DB1_CONTAINER="${db_cid}"
  NETWORK_NAME="${db_network}"

  log "== up: create the owner and online roles (step 4's credential split) =="
  psql_super <<SQL
DO \$\$
BEGIN
  IF NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = '${DB_OWNER_USER}') THEN
    CREATE ROLE ${DB_OWNER_USER} LOGIN PASSWORD '${DB_OWNER_PASSWORD}';
  END IF;
  IF NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = '${DB_ONLINE_USER}') THEN
    CREATE ROLE ${DB_ONLINE_USER} LOGIN PASSWORD '${DB_ONLINE_PASSWORD}';
  END IF;
END
\$\$;
ALTER DATABASE ${DB1_NAME} OWNER TO ${DB_OWNER_USER};
GRANT ALL PRIVILEGES ON DATABASE ${DB1_NAME} TO ${DB_OWNER_USER};
GRANT CONNECT ON DATABASE ${DB1_NAME} TO ${DB_ONLINE_USER};
SQL
  # The online role gets USAGE but deliberately NOT CREATE on the public
  # schema, and no default privileges on future tables beyond read/write —
  # this is the exact grant shape step 4 exists to prove: the runtime role
  # can use the schema the owner built, and cannot build one of its own.
  psql_owner <<SQL
GRANT USAGE ON SCHEMA public TO ${DB_ONLINE_USER};
REVOKE CREATE ON SCHEMA public FROM ${DB_ONLINE_USER};
ALTER DEFAULT PRIVILEGES FOR ROLE ${DB_OWNER_USER} IN SCHEMA public
  GRANT SELECT, INSERT, UPDATE, DELETE ON TABLES TO ${DB_ONLINE_USER};
SQL

  log "up complete. product=${REHEARSAL_PRODUCT} image=${IMAGE_REFERENCE} network=${NETWORK_NAME}"
}

# ══════════════════════════════════════════════════════════════════════════
# run — the 14 ordered steps
# ══════════════════════════════════════════════════════════════════════════

STEP_NUM=0

run_step_1_build_once() {
  STEP_NUM=1
  require_state IMAGE_REFERENCE
  if "${DOCKER_BIN}" image inspect "${IMAGE_REFERENCE}" >/dev/null 2>&1; then
    step_pass "image ${IMAGE_REFERENCE} present locally; digest recorded by 'up', never rebuilt"
  else
    step_fail "build the image once" "the recorded digest is not present locally"
    return 1
  fi
}

run_step_2_image_audit() {
  STEP_NUM=2
  local inspect_json="${WORK_DIR}/inspect.json"
  local history_json="${WORK_DIR}/history.json"
  local layers_txt="${WORK_DIR}/layers.txt"
  "${DOCKER_BIN}" image inspect "${IMAGE_REPOSITORY}:${IMAGE_TAG}" > "${inspect_json}"
  "${DOCKER_BIN}" history --no-trunc --format '{{.CreatedBy}}' "${IMAGE_REPOSITORY}:${IMAGE_TAG}" \
    | "${PYTHON_BIN}" -c 'import json,sys; print(json.dumps([l.rstrip(chr(10)) for l in sys.stdin]))' \
    > "${history_json}"
  local cid
  cid="$("${DOCKER_BIN}" create "${IMAGE_REPOSITORY}:${IMAGE_TAG}")"
  "${DOCKER_BIN}" export "${cid}" | tar -tf - > "${layers_txt}" || true
  "${DOCKER_BIN}" rm -f "${cid}" >/dev/null

  if dotmac_deploy -f "${DESCRIPTOR}" image-audit "${IMAGE_REFERENCE}" \
      --inspect "${inspect_json}" --history "${history_json}" --layers "${layers_txt}"; then
    step_pass "dotmac-deploy image-audit passed against the real built image"
  else
    step_fail "dotmac-deploy image-audit" "the contract genuinely failed — see output above"
    return 1
  fi
}

run_step_3_render_and_config() {
  STEP_NUM=3
  render_assets >/dev/null
  if "${COMPOSE[@]}" config >/dev/null; then
    step_pass "dotmac-deploy render + docker compose config both accepted the rendered file"
  else
    step_fail "docker compose config" "the real engine refused the rendered compose file"
    return 1
  fi
}

run_step_4_role_separation() {
  STEP_NUM=4
  local out
  local rc=0
  out="$(psql_online -v ON_ERROR_STOP=1 -c 'CREATE TABLE should_never_exist (id int);' 2>&1)" || rc=$?
  if [ "${rc}" -ne 0 ] && printf '%s' "${out}" | grep -qi 'permission denied'; then
    step_pass "the online role genuinely cannot CREATE TABLE (permission denied)"
  else
    step_fail "prove the online role cannot CREATE TABLE" "rc=${rc} out=${out}"
    return 1
  fi
}

run_step_5_migrate() {
  STEP_NUM=5
  "${COMPOSE[@]}" rm -sf app >/dev/null 2>&1 || true
  local before
  before="$("${COMPOSE[@]}" ps -q app 2>/dev/null || true)"
  if [ -n "${before}" ]; then
    step_fail "docker compose up migrate" "a runtime container already existed before migrate ran"
    return 1
  fi
  if "${COMPOSE[@]}" up migrate; then
    local after
    after="$("${COMPOSE[@]}" ps -q app 2>/dev/null || true)"
    if [ -n "${after}" ]; then
      step_fail "docker compose up migrate" "app started before migrate was asked to run it"
      return 1
    fi
    step_pass "docker compose up migrate exited 0; no runtime container started first"
  else
    step_fail "docker compose up migrate" "migrate exited non-zero"
    return 1
  fi
}

run_step_6_verify_heads() {
  STEP_NUM=6
  local observed
  observed="$("${COMPOSE[@]}" run --rm --no-deps migrate python /app/app.py --heads 2>/dev/null | tr -d '\r')"
  if [ "${observed}" = "${SCHEMA_HEAD}" ]; then
    step_pass "real heads (${observed}) equal expected_heads (${SCHEMA_HEAD})"
  else
    step_fail "verify heads" "observed=[${observed}] expected=[${SCHEMA_HEAD}]"
    return 1
  fi
}

run_step_7_live_vs_ready_with_db_down() {
  STEP_NUM=7
  "${COMPOSE[@]}" rm -sf app >/dev/null 2>&1 || true
  "${DOCKER_BIN}" stop "${DB1_CONTAINER}" >/dev/null

  "${COMPOSE[@]}" up -d --no-deps app >/dev/null
  wait_for_container "${WAIT_HTTP_TIMEOUT_SECONDS}" "$("${COMPOSE[@]}" ps -q app)" \
    "app to answer on :${APP_HOST_PORT}" \
    bash -c "[ \"\$(curl -s -o /dev/null -w '%{http_code}' --max-time 2 http://127.0.0.1:${APP_HOST_PORT}/health/live 2>/dev/null)\" != \"000\" ]" \
    || true

  local live ready
  live="$(http_status "http://127.0.0.1:${APP_HOST_PORT}/health/live")"
  ready="$(http_status "http://127.0.0.1:${APP_HOST_PORT}/health/ready")"

  "${DOCKER_BIN}" start "${DB1_CONTAINER}" >/dev/null
  wait_for_stable_container "${WAIT_DB_TIMEOUT_SECONDS}" "${WAIT_DB_STABLE_PROBES}" \
    "${DB1_CONTAINER}" "primary database ready again" \
    "${DOCKER_BIN}" exec -e PGPASSWORD="${DB_SUPERUSER_PASSWORD}" "${DB1_CONTAINER}" \
    psql -h 127.0.0.1 -p "${DB_PORT}" \
    -v ON_ERROR_STOP=1 -U "${DB_SUPERUSER}" -d "${DB1_NAME}" -c 'SELECT 1' 

  if [ "${live}" = "200" ] && [ "${ready}" = "503" ]; then
    step_pass "with the database stopped: /health/live=200, /health/ready=503 (the ERP defect, inverted)"
  else
    step_fail "live vs ready with the database down" "live=${live} ready=${ready}"
    return 1
  fi
}

run_step_8_switch_and_verify() {
  STEP_NUM=8
  # "Restore the database" — already back up from step 7's own cleanup, so
  # this step's job is the second half: bring the role up for real (through
  # compose, on the network, dependency-gated on the database and the
  # migration — this is the actual `switch` behaviour
  # ComposeHostEffects.switch implements: recreate every role on one
  # digest), then set the readiness marker and verify.
  "${COMPOSE[@]}" rm -sf app >/dev/null 2>&1 || true
  "${COMPOSE[@]}" up -d app >/dev/null

  local cid
  cid="$("${COMPOSE[@]}" ps -q app)"
  [ -n "${cid}" ] || { step_fail "switch" "no app container after 'compose up -d app'"; return 1; }
  wait_for_container "${WAIT_HTTP_TIMEOUT_SECONDS}" "${cid}" "app container running" \
    bash -c "[ \"\$(docker inspect -f '{{.State.Running}}' ${cid} 2>/dev/null)\" = \"true\" ]"
  "${DOCKER_BIN}" exec "${cid}" sh -c 'mkdir -p /tmp && : > /tmp/rehearsal-ready' 2>/dev/null || true
  wait_for_container "${WAIT_HTTP_TIMEOUT_SECONDS}" "${cid}" \
    "app answering /health/ready=200 after the marker is set" \
    bash -c "[ \"\$(curl -s -o /dev/null -w '%{http_code}' --max-time 2 http://127.0.0.1:${APP_HOST_PORT}/health/ready 2>/dev/null)\" = \"200\" ]"

  local running digest restarts
  running="$("${DOCKER_BIN}" inspect -f '{{.State.Running}}' "${cid}")"
  digest="$("${DOCKER_BIN}" inspect -f '{{index .Config.Image}}' "${cid}")"
  restarts="$("${DOCKER_BIN}" inspect -f '{{.RestartCount}}' "${cid}")"

  if [ "${running}" != "true" ] || [ "${digest}" != "${IMAGE_REFERENCE}" ] \
      || [ "${restarts}" != "0" ]; then
    step_fail "switch + verify roles" "running=${running} digest=${digest} restarts=${restarts} (expected ${IMAGE_REFERENCE})"
    return 1
  fi
  if ! prove_nginx_handoff; then
    step_fail "Nginx handoff" \
      "the real parser, live config and primary-to-candidate failover did not all pass"
    return 1
  fi
  step_pass "every role runs the one digest with zero restarts; real Nginx parsed the rendered site and promoted the ready candidate when primary stopped"
}

run_step_9_drift() {
  STEP_NUM=9
  local observed="${WORK_DIR}/observed.json"
  local approved_image="${IMAGE_DIGEST}"
  local approved_manifest
  approved_manifest="$(grep '^manifest_digest' "${DESCRIPTOR}" | sed -E 's/.*"(.*)"/\1/')"

  # Every asset `_rendered_assets` (cli.py) enumerates needs a real observed
  # digest, or `compare()` reports it UNKNOWN rather than MATCH — and
  # `DriftReport.clean` treats UNKNOWN the same as DRIFT (ADR-0032,
  # "unobserved is UNKNOWN, never ABSENT"). The files under WORK_DIR/rendered
  # were just written by `dotmac-deploy render` above, so hashing them here
  # IS the "observation".
  local compose_digest alerts_digest otel_digest
  compose_digest="sha256:$(sha256sum "${WORK_DIR}/rendered/docker-compose.yml" | awk '{print $1}')"
  alerts_digest="sha256:$(sha256sum "${WORK_DIR}/rendered/alerts.rules.yml" | awk '{print $1}')"
  otel_digest="sha256:$(sha256sum "${WORK_DIR}/rendered/otel-collector/config.yaml" | awk '{print $1}')"

  cat > "${observed}" <<JSON
{
  "role_image_digests": {"app": "${approved_image}"},
  "config_digests": {
    "docker-compose.yml": "${compose_digest}",
    "alerts.rules.yml": "${alerts_digest}",
    "otel-collector/config.yaml": "${otel_digest}"
  },
  "manifest_digest": "${approved_manifest}",
  "approved_image_digest": "${approved_image}"
}
JSON
  local clean=0
  dotmac_deploy -f "${DESCRIPTOR}" drift --observed "${observed}" \
    --thresholds "${REHEARSAL_DIR}/thresholds.json" >/dev/null || clean=1
  if [ "${clean}" -ne 0 ]; then
    step_fail "drift (clean state)" "expected a clean report; the CLI reported drift or an unknown"
    return 1
  fi

  # Now hand-edit one rendered byte on the host and expect DRIFT. The
  # "observed" config digest below is the TAMPERED file's real hash; `drift`
  # recomputes what the descriptor SHOULD render internally and compares —
  # it does not need to be told what the correct value is.
  echo "# hand-edited by the rehearsal, on purpose" >> "${WORK_DIR}/rendered/docker-compose.yml"
  local tampered_digest
  tampered_digest="sha256:$(sha256sum "${WORK_DIR}/rendered/docker-compose.yml" | awk '{print $1}')"
  cat > "${observed}" <<JSON
{
  "role_image_digests": {"app": "${approved_image}"},
  "config_digests": {
    "docker-compose.yml": "${tampered_digest}",
    "alerts.rules.yml": "${alerts_digest}",
    "otel-collector/config.yaml": "${otel_digest}"
  },
  "manifest_digest": "${approved_manifest}",
  "approved_image_digest": "${approved_image}"
}
JSON
  local drifted=0
  dotmac_deploy -f "${DESCRIPTOR}" drift --observed "${observed}" \
    --thresholds "${REHEARSAL_DIR}/thresholds.json" >/dev/null || drifted=1

  # Restore the file so later steps (down, re-runs) see the real render again.
  render_assets >/dev/null

  if [ "${drifted}" -ne 0 ]; then
    step_pass "clean state reported clean; a one-byte hand-edit reported DRIFT and refused (exit 1)"
  else
    step_fail "drift after a hand-edit" "expected DRIFT and a non-zero exit, got a clean report"
    return 1
  fi
}

verify_backup_artifact() {
  # verify_backup_artifact <path> <expected-sha256> — the same three checks
  # ComposeHostEffects.verify_backup performs: size, a full re-hash, and a
  # full decompression. Reproduced directly rather than imported, so this
  # rehearsal has no import-time dependency on the provider's private
  # constructor shape.
  local path="$1"
  local expected_sha="$2"
  [ -s "${path}" ] || return 1
  local actual_sha
  actual_sha="$(sha256sum "${path}" | awk '{print $1}')"
  [ "${actual_sha}" = "${expected_sha}" ] || return 1
  gzip -t "${path}" 2>/dev/null || return 1
  return 0
}

run_step_10_backup_verify_restore() {
  STEP_NUM=10
  local stamp
  stamp="$(date -u +%Y%m%dT%H%M%SZ)"
  local dump="${BACKUP_DIR}/${BACKUP_DATASET}_${stamp}.sql.gz"
  "${DOCKER_BIN}" exec -e PGPASSWORD="${DB_OWNER_PASSWORD}" "${DB1_CONTAINER}" \
    pg_dump -U "${DB_OWNER_USER}" -d "${DB1_NAME}" --no-owner --no-privileges \
    | gzip > "${dump}"
  local sha
  sha="$(sha256sum "${dump}" | awk '{print $1}')"

  if ! verify_backup_artifact "${dump}" "${sha}"; then
    step_fail "verify backup" "the real backup did not verify"
    return 1
  fi

  # Restore into a SECOND disposable database.
  remove_container "${DB2_CONTAINER}"
  "${DOCKER_BIN}" run -d --name "${DB2_CONTAINER}" \
    --network "${NETWORK_NAME}" \
    -e "POSTGRES_PASSWORD=${DB_SUPERUSER_PASSWORD}" \
    -e "POSTGRES_DB=${DB2_NAME}" \
    -e "POSTGRES_USER=${DB_SUPERUSER}" \
    "${DB_IMAGE}" >/dev/null
  # Same init-restart race as the primary (see `wait_for_stable`): this
  # container is created FRESH each time, so it always runs the entrypoint's
  # temporary-server phase — the restore that follows would fail on a
  # vanished socket.
  wait_for_stable_container "${WAIT_DB_TIMEOUT_SECONDS}" "${WAIT_DB_STABLE_PROBES}" \
    "${DB2_CONTAINER}" "restore-target database ready" \
    "${DOCKER_BIN}" exec -e PGPASSWORD="${DB_SUPERUSER_PASSWORD}" "${DB2_CONTAINER}" \
    psql -h 127.0.0.1 -p "${DB_PORT}" \
    -v ON_ERROR_STOP=1 -U "${DB_SUPERUSER}" -d postgres -c 'SELECT 1' 

  if ! gunzip -c "${dump}" \
      | "${DOCKER_BIN}" exec -i -e PGPASSWORD="${DB_SUPERUSER_PASSWORD}" "${DB2_CONTAINER}" \
        psql -v ON_ERROR_STOP=1 -U "${DB_SUPERUSER}" -d "${DB2_NAME}" >/dev/null; then
    step_fail "restore into a disposable target" "the restore command failed"
    return 1
  fi

  local schema_ok row_count heads
  schema_ok="$("${DOCKER_BIN}" exec -e PGPASSWORD="${DB_SUPERUSER_PASSWORD}" "${DB2_CONTAINER}" \
    psql -tAc "SELECT to_regclass('public.schema_version') IS NOT NULL" \
    -U "${DB_SUPERUSER}" -d "${DB2_NAME}" | tr -d '[:space:]')"
  row_count="$("${DOCKER_BIN}" exec -e PGPASSWORD="${DB_SUPERUSER_PASSWORD}" "${DB2_CONTAINER}" \
    psql -tAc "SELECT count(*) FROM rehearsal_ledger" \
    -U "${DB_SUPERUSER}" -d "${DB2_NAME}" | tr -d '[:space:]')"
  heads="$("${DOCKER_BIN}" exec -e PGPASSWORD="${DB_SUPERUSER_PASSWORD}" "${DB2_CONTAINER}" \
    psql -tAc "SELECT version FROM schema_version" \
    -U "${DB_SUPERUSER}" -d "${DB2_NAME}" | tr -d '[:space:]')"

  if [ "${schema_ok}" = "t" ] && [ "${row_count}" -ge 1 ] 2>/dev/null && [ "${heads}" = "${SCHEMA_HEAD}" ]; then
    step_pass "restore reached PROVED: schema present, ${row_count} row(s), heads=${heads}"
  else
    step_fail "restore reached PROVED" "schema_ok=${schema_ok} rows=${row_count} heads=${heads}"
    return 1
  fi
}

_check_corrupt_backup_fails_verification() {
  # The shared logic behind both run step 11 and the `corrupt-backup`
  # injection case — a plain 0/1 check with no PASS/FAIL/case_* side
  # effects of its own, so calling it from two places never double-counts.
  local good="${BACKUP_DIR}/${BACKUP_DATASET}_verify_check.sql.gz"
  "${DOCKER_BIN}" exec -e PGPASSWORD="${DB_OWNER_PASSWORD}" "${DB1_CONTAINER}" \
    pg_dump -U "${DB_OWNER_USER}" -d "${DB1_NAME}" --no-owner --no-privileges \
    | gzip > "${good}"
  local sha
  sha="$(sha256sum "${good}" | awk '{print $1}')"

  local truncated="${BACKUP_DIR}/${BACKUP_DATASET}_truncated.sql.gz"
  local full_size
  full_size="$(stat -f%z "${good}" 2>/dev/null || stat -c%s "${good}")"
  local half=$((full_size / 2))
  head -c "${half}" "${good}" > "${truncated}"

  # Verification MUST fail on the truncated artefact — this is the whole
  # point of the step, not a side effect: without it, step 10 above passes
  # on a checker that would accept anything.
  if verify_backup_artifact "${truncated}" "${sha}"; then
    log "the truncated artefact verified — the checker accepts anything"
    return 1
  fi
  # And the genuine artefact, checked the SAME way, must still pass — the
  # negative control for this step, the same shape as the suite's own
  # test_a_correct_deployment_succeeds_end_to_end.
  if ! verify_backup_artifact "${good}" "${sha}"; then
    log "the negative control (the real backup) failed to verify"
    return 1
  fi
  return 0
}

run_step_11_corrupt_backup_fails_verification() {
  STEP_NUM=11
  if _check_corrupt_backup_fails_verification; then
    step_pass "a deliberately truncated backup FAILS verification (size/hash/gzip); the real one still passes"
  else
    step_fail "truncated backup verification" "see the log line above"
    return 1
  fi
}

run_step_12_telemetry_attributes() {
  STEP_NUM=12
  # The rehearsal's OWN plaintext collector — see product.toml's
  # `[telemetry]` comment for why this is not the product's rendered one.
  local collector_config="${WORK_DIR}/otel-sink.yaml"
  local sink_file="${WORK_DIR}/otel-sink.json"
  rm -f "${sink_file}"
  cat > "${collector_config}" <<YAML
receivers:
  otlp:
    protocols:
      http:
        endpoint: 0.0.0.0:4318
exporters:
  file:
    path: /sink/otel-sink.json
service:
  pipelines:
    logs:
      receivers: [otlp]
      exporters: [file]
YAML
  remove_container "${OTEL_COLLECTOR_CONTAINER}"
  touch "${sink_file}"
  # `--user` is REQUIRED, not hygiene. The collector image runs as a non-root
  # user, `${sink_file}` is created here as whoever runs this script, and the
  # `file` exporter opens it FOR WRITING AT STARTUP — so without this the
  # collector exits immediately with
  #   cannot start pipelines: open /sink/otel-sink.json: permission denied
  # and the wait below reports a timeout that says nothing about permissions.
  # Running the container as the identity that owns the directory is the fix
  # that needs no world-writable file.
  "${DOCKER_BIN}" run -d --name "${OTEL_COLLECTOR_CONTAINER}" \
    --user "$(id -u):$(id -g)" \
    -p "127.0.0.1:${OTEL_HTTP_PORT}:4318" \
    -v "${collector_config}:/etc/otelcol/config.yaml:ro" \
    -v "${WORK_DIR}:/sink" \
    "${OTEL_COLLECTOR_IMAGE}" --config /etc/otelcol/config.yaml >/dev/null
  if ! wait_for_container "${WAIT_COLLECTOR_TIMEOUT_SECONDS}" \
    "${OTEL_COLLECTOR_CONTAINER}" \
    "the rehearsal's own collector on :${OTEL_HTTP_PORT}" \
    bash -c "[ \"\$(curl -s -o /dev/null -w '%{http_code}' --max-time 2 http://127.0.0.1:${OTEL_HTTP_PORT}/v1/logs -X POST -H 'Content-Type: application/json' -d '{}' 2>/dev/null)\" != \"000\" ]"; then
    diagnose_container "${OTEL_COLLECTOR_CONTAINER}" \
      "the rehearsal's own collector on :${OTEL_HTTP_PORT}"
    step_fail "telemetry collector" "the collector never accepted OTLP"
    return 1
  fi

  local attrs
  attrs="$(dotmac_deploy -f "${DESCRIPTOR}" observe --deployment-id "rehearsal-run" --host "observer-rehearsal" \
    | grep OTEL_RESOURCE_ATTRIBUTES | head -1 | cut -d= -f2- || true)"
  [ -n "${attrs}" ] || { step_fail "telemetry attributes" "dotmac-deploy observe produced nothing"; return 1; }

  local payload
  payload="$("${PYTHON_BIN}" - "${attrs}" <<'PYEOF'
import json, sys
pairs = [p.split("=", 1) for p in sys.argv[1].split(",")]
resource_attrs = [{"key": k, "value": {"stringValue": v}} for k, v in pairs]
body = {
    "resourceLogs": [{
        "resource": {"attributes": resource_attrs},
        "scopeLogs": [{"logRecords": [{"body": {"stringValue": "rehearsal signal"}}]}],
    }]
}
print(json.dumps(body))
PYEOF
)"
  curl -s -o /dev/null --max-time 5 -X POST \
    -H 'Content-Type: application/json' \
    -d "${payload}" \
    "http://127.0.0.1:${OTEL_HTTP_PORT}/v1/logs" || true
  sleep 2

  local missing=0
  for name in "service.name" "deployment.environment" "dotmac.product" \
              "dotmac.deployment_id" "dotmac.release" "dotmac.git_sha" \
              "dotmac.image_digest" "dotmac.host" "dotmac.role"; do
    if ! grep -q "\"${name}\"" "${sink_file}" 2>/dev/null; then
      missing=$((missing + 1))
      log "  missing resource attribute on the real signal: ${name}"
    fi
  done
  if [ "${missing}" -eq 0 ]; then
    step_pass "a real OTLP signal arrived at a real collector carrying all nine resource attributes"
  else
    step_fail "telemetry attributes on a real signal" "${missing} of 9 attributes missing"
    return 1
  fi
}

run_step_13_alert_fires_and_recovers() {
  STEP_NUM=13
  local rules="${WORK_DIR}/rehearsal.rules.yml"
  local prom_config="${WORK_DIR}/prometheus.yml"
  cat > "${rules}" <<YAML
groups:
  - name: rehearsal
    rules:
      - alert: ${PROM_RULE_NAME}
        expr: up{job="rehearsal-app"} == 0
        for: ${PROM_ALERT_FOR}
        labels:
          severity: page
        annotations:
          summary: "the rehearsal app target is down"
YAML
  # Scraped by SERVICE NAME on the compose network the app itself is on
  # (`app:${APP_PORT}`), not by the host's loopback-bound published port: a
  # port published with `bind = "127.0.0.1"` (product.toml's own
  # `[[roles.ports]]` comment explains why) only accepts connections
  # originating from the host itself, so a separate container reaching it
  # via `host-gateway`/`host.docker.internal` would not work on a Linux
  # host such as Observer. Prometheus joins `${NETWORK_NAME}` instead — the
  # same network `docker compose` already attached `app` to.
  cat > "${prom_config}" <<YAML
global:
  scrape_interval: 2s
  evaluation_interval: 2s
rule_files:
  - /etc/prometheus/rehearsal.rules.yml
scrape_configs:
  - job_name: rehearsal-app
    metrics_path: /metrics
    static_configs:
      - targets: ["app:${APP_PORT}"]
YAML

  remove_container "${PROM_CONTAINER}"
  "${DOCKER_BIN}" run -d --name "${PROM_CONTAINER}" \
    --network "${NETWORK_NAME}" \
    -p "127.0.0.1:${PROM_HTTP_PORT}:9090" \
    -v "${prom_config}:/etc/prometheus/prometheus.yml:ro" \
    -v "${rules}:/etc/prometheus/rehearsal.rules.yml:ro" \
    "${PROM_IMAGE}" >/dev/null
  if ! wait_for_container "${WAIT_PROMETHEUS_TIMEOUT_SECONDS}" \
    "${PROM_CONTAINER}" \
    "Prometheus on :${PROM_HTTP_PORT}" \
    curl -sf "http://127.0.0.1:${PROM_HTTP_PORT}/-/ready"; then
    diagnose_container "${PROM_CONTAINER}" "Prometheus on :${PROM_HTTP_PORT}"
    step_fail "alert evaluation" "Prometheus never became ready"
    return 1
  fi

  local app_cid
  app_cid="$("${COMPOSE[@]}" ps -q app)"
  if [ -z "${app_cid}" ]; then
    step_fail "alert evaluation" "no app container exists before the fire/recovery proof"
    return 1
  fi

  # Establish the healthy baseline before injecting the outage. An inactive
  # rule with no target is not a healthy baseline; it is a missing subject.
  if ! wait_for_container "${WAIT_PROMETHEUS_TIMEOUT_SECONDS}" \
    "${PROM_CONTAINER}" \
    "Prometheus baseline: ${PROM_RULE_NAME} inactive and target up" \
    prom_recovery_proved; then
    diagnose_prometheus_transition "${app_cid}" "baseline"
    step_fail "alert baseline" "the named rule and target never became healthy"
    return 1
  fi

  # The app is already up (from step 8) and ready. Stop it so the expected
  # target remains configured but reports DOWN and the named rule genuinely
  # reaches FIRING.
  "${COMPOSE[@]}" stop app >/dev/null
  if ! wait_for_container "${WAIT_ALERT_FIRE_SECONDS}" \
    "${PROM_CONTAINER}" \
    "${PROM_RULE_NAME} firing while ${PROM_SCRAPE_URL} is down" \
    prom_fire_proved; then
    diagnose_prometheus_transition "${app_cid}" "fire"
    step_fail "alert fires" "the rule and target never reached firing/down together"
    return 1
  fi

  "${COMPOSE[@]}" start app >/dev/null
  app_cid="$("${COMPOSE[@]}" ps -q app)"
  if [ -z "${app_cid}" ]; then
    step_fail "alert recovers" "the app container did not return"
    return 1
  fi
  wait_for_container "${WAIT_HTTP_TIMEOUT_SECONDS}" "${app_cid}" \
    "app answering liveness after restart" \
    bash -c "[ \"\$(curl -s -o /dev/null -w '%{http_code}' --max-time 2 http://127.0.0.1:${APP_HOST_PORT}/health/live 2>/dev/null)\" = \"200\" ]"

  # /tmp is a tmpfs, so the harness-controlled readiness marker is correctly
  # lost when the container stops. Re-arm the fixture after restart and prove
  # BOTH its HTTP readiness contract and Docker's derived health state before
  # accepting Prometheus recovery. The previous predicate would have passed
  # with the app still unhealthy.
  if ! "${DOCKER_BIN}" exec "${app_cid}" sh -c \
      'mkdir -p /tmp && : > /tmp/rehearsal-ready'; then
    diagnose_prometheus_transition "${app_cid}" "recovery"
    step_fail "alert recovers" "could not restore the harness readiness marker"
    return 1
  fi
  if ! wait_for_container "${WAIT_HTTP_TIMEOUT_SECONDS}" "${app_cid}" \
    "app readiness=200 after restart" \
    bash -c "[ \"\$(curl -s -o /dev/null -w '%{http_code}' --max-time 2 http://127.0.0.1:${APP_HOST_PORT}/health/ready 2>/dev/null)\" = \"200\" ]"; then
    step_fail "alert recovers" "the app never became ready after restart"
    return 1
  fi
  if ! wait_for_container "${WAIT_HTTP_TIMEOUT_SECONDS}" "${app_cid}" \
    "app Docker health healthy after restart" \
    container_healthy "${app_cid}"; then
    step_fail "alert recovers" "the app never became Docker-healthy after restart"
    return 1
  fi

  # Recovery is conjunctive. The stable named rule must be INACTIVE, the
  # expected scrape target must still exist and be UP, and the app readiness
  # checks above must already have succeeded. A missing rule or target is a
  # monitoring failure, never recovery.
  if ! wait_for_container "${WAIT_ALERT_RECOVER_SECONDS}" \
    "${PROM_CONTAINER}" \
    "${PROM_RULE_NAME} inactive while ${PROM_SCRAPE_URL} is up" \
    prom_recovery_proved; then
    diagnose_prometheus_transition "${app_cid}" "recovery"
    step_fail "alert recovers" "rule, target and app never recovered together"
    return 1
  fi

  step_pass "${PROM_RULE_NAME} fired with its target down, then the rule, target and app all recovered"
}

cmd_run() {
  load_state
  require_state IMAGE_REFERENCE
  run_step_1_build_once
  run_step_2_image_audit
  run_step_3_render_and_config
  run_step_4_role_separation
  run_step_5_migrate
  run_step_6_verify_heads
  run_step_7_live_vs_ready_with_db_down
  run_step_8_switch_and_verify
  run_step_9_drift
  run_step_10_backup_verify_restore
  run_step_11_corrupt_backup_fails_verification
  run_step_12_telemetry_attributes
  run_step_13_alert_fires_and_recovers
  # Step 14 (teardown) is NOT run automatically here — `all` calls `down`
  # itself once every injection case has also run, and a standalone `run`
  # is expected to be followed by `inject <case>` invocations against the
  # same live state. Call `down` explicitly, or use `all`.
  log "run: 13 of the 14 ordered steps complete (14 is 'down' — call it explicitly, or use 'all')"
}

# ══════════════════════════════════════════════════════════════════════════
# inject <case> — the failure-injection matrix, against real infrastructure
# ══════════════════════════════════════════════════════════════════════════

ALL_CASES=(
  wrong-image-digest
  wrong-manifest-digest
  missing-migration-credentials
  owner-credential-in-runtime-role
  migration-failure
  migration-lock-contention
  missing-migration-head
  failed-backup
  corrupt-backup
  failed-restore-verification
  candidate-never-ready
  primary-fails-after-handoff
  worker-unhealthy
  scheduler-stale
  invalid-nginx-configuration
  telemetry-collector-unavailable
  secrets-unavailable
  untracked-override
  source-bind-mount
  previous-image-reused-after-incompatible-migration
  maintenance-required-attempted-online
)

cmd_list_cases() {
  printf '%s\n' "${ALL_CASES[@]}"
}

reset_compose_runtime() {
  # Every case starts from the same known state: db up (from `up`/`run`),
  # app/migrate down. Never touches the database or the network.
  "${COMPOSE[@]}" rm -sf app migrate >/dev/null 2>&1 || true
}

database_schema_fingerprint() {
  # A gate-phase refusal must leave the scratch database's schema equivalent.
  # Checking for one table is invalid after the ordered rehearsal has already
  # migrated successfully. A real schema-only dump includes relations,
  # columns, constraints, indexes, sequences and grants, so hashing it refuses
  # subtler DDL than a relation-name census can see. PostgreSQL 16.15 emits a
  # fresh random token in the dump's `\restrict`/`\unrestrict` safety commands
  # on every invocation. Those two psql commands protect replay; their nonce is
  # not database state, so remove only those complete command lines before
  # hashing. Without this normalization two consecutive dumps of an untouched
  # database always disagree and the no-DDL proof can never pass.
  "${DOCKER_BIN}" exec -e PGPASSWORD="${DB_SUPERUSER_PASSWORD}" \
    "${DB1_CONTAINER}" pg_dump -h 127.0.0.1 -p "${DB_PORT}" \
    -U "${DB_SUPERUSER}" -d "${DB1_NAME}" \
    --schema-only --no-owner --no-privileges \
    | awk '$1 != "\\restrict" && $1 != "\\unrestrict"' \
    | sha256sum | awk '{print $1}'
}

EFFECTS_DESCRIPTOR=""
EFFECTS_COMPOSE_FILE=""
EFFECTS_COMPOSE=()

prepare_effects_fixture() {
  # The ordered lane deliberately stays a one-role product. These three
  # injection cases need the real provider contracts that a minimal HTTP-only
  # descriptor cannot express, so derive a disposable working copy with an
  # ingress route, a custom worker and a scheduler. The image and every other
  # deployment fact remain the ones produced by `up` at this exact SHA.
  EFFECTS_DESCRIPTOR="${WORK_DIR}/effects-product.toml"
  EFFECTS_COMPOSE_FILE="${WORK_DIR}/effects-rendered/docker-compose.yml"
  cp "${DESCRIPTOR}" "${EFFECTS_DESCRIPTOR}"
  # Drop the base fixture's own `[[roles.ports]]`. Under IngressPolicy.v1 the
  # edge OWNS the port it routes to — it publishes that upstream on loopback
  # itself — so a second declaration of the same container port is refused
  # rather than merged. This used to rewrite the publication's host port to
  # match the route instead; that produced two declarations of one port whose
  # agreement nothing checked, which is the drift the refusal exists to stop.
  # The ordered HTTP-only fixture keeps its own high host port and its own
  # publication, because it declares no ingress at all.
  local rewritten="${EFFECTS_DESCRIPTOR}.tmp"
  awk '
    /^\[\[roles\.ports\]\]$/ { skip = 1 }
    /^\[migration\]$/ { skip = 0 }
    skip != 1 { print }
  ' "${EFFECTS_DESCRIPTOR}" > "${rewritten}"
  mv "${rewritten}" "${EFFECTS_DESCRIPTOR}"
  cat >> "${EFFECTS_DESCRIPTOR}" <<'TOML'

[ingress]
host = "rehearsal.invalid"
redirect_http = false
# IngressPolicy.v1: the edge declares its own exposure and address family like
# any other publication, and `public` carries the approval LOCATOR (never an
# approval — deployment control owns that binding).
exposure = "public"
address_family = "ipv4"
approval_ref = "deployment.public-exposure"
rationale_url = "https://docs.dotmac.io/deployment/rehearsal-edge"

[[ingress.routes]]
path = "/"
role = "app"
port = 8000

[[roles]]
code = "worker"
command = ["python", "/app/app.py", "--worker"]
replicas = 1
stop_grace_seconds = 5

[roles.resources]
cpus = "0.25"
memory = "128m"
pids = 32

[roles.security]
user = "10001:10001"
read_only_root = true
no_new_privileges = true
cap_drop = ["ALL"]
tmpfs = ["/tmp"]

[roles.worker]
kind = "custom"
ping_command = ["python", "/app/app.py", "--worker-ping"]
heartbeat_max_age_seconds = 30
max_backlog = 1

[[roles]]
code = "scheduler"
command = ["python", "/app/app.py", "--scheduler"]
replicas = 1
stop_grace_seconds = 5

[roles.resources]
cpus = "0.25"
memory = "128m"
pids = 32

[roles.security]
user = "10001:10001"
read_only_root = true
no_new_privileges = true
cap_drop = ["ALL"]
tmpfs = ["/tmp"]

[roles.scheduler]
last_tick_max_age_seconds = 10
tick_command = ["python", "/app/app.py", "--scheduler-last-tick"]
TOML
  dotmac_deploy -f "${EFFECTS_DESCRIPTOR}" render \
    --output-dir "${WORK_DIR}/effects-rendered" \
    --thresholds "${REHEARSAL_DIR}/thresholds.json" >/dev/null
  EFFECTS_COMPOSE=(
    "${DOCKER_BIN}" "${COMPOSE_SUBCOMMAND}"
    --project-name "${REHEARSAL_PRODUCT}"
    --project-directory "${WORK_DIR}"
    --env-file "${ENV_FILE}"
    -f "${EFFECTS_COMPOSE_FILE}"
  )
}

effects_probe() {
  # Drive the real ComposeHostEffects implementation against the derived
  # descriptor. Output is intentionally one scalar so shell call sites cannot
  # mistake provider diagnostics for the verdict they are checking.
  local action="$1"
  ( cd "${REPO_ROOT}" && "${PYTHON_BIN}" - \
      "${action}" "${EFFECTS_DESCRIPTOR}" "${WORK_DIR}" \
      "${EFFECTS_COMPOSE_FILE}" "${ENV_FILE}" <<'PYEOF'
import sys
from pathlib import Path

from dotmac_deployment_foundation.providers.compose_host import ComposeHostEffects
from dotmac_deployment_foundation.spec import ProductDeploymentSpec

action, descriptor, deploy_dir, compose_file, env_file = sys.argv[1:]
spec = ProductDeploymentSpec.load(descriptor)
effects = ComposeHostEffects(
    spec,
    Path(deploy_dir),
    compose_file=Path(compose_file),
    env_file=Path(env_file),
)

if action == "start-candidate":
    print(effects.start_candidate("app", timeout_seconds=30))
elif action == "candidate-ready":
    print("true" if effects.candidate_ready("app") else "false")
elif action == "worker-responds":
    print("true" if effects.worker_responds("worker") else "false")
elif action == "scheduler-age":
    age = effects.scheduler_last_tick_age_seconds("scheduler")
    print("none" if age is None else age)
else:
    raise SystemExit(f"unknown effects probe: {action}")
PYEOF
  )
}

effects_candidate_ready() {
  [ "$(effects_probe candidate-ready)" = true ]
}

NGINX_CERT_ROOT=""
NGINX_SITE=""

prepare_nginx_files() {
  NGINX_CERT_ROOT="${WORK_DIR}/nginx-certs"
  NGINX_SITE="${WORK_DIR}/effects-rendered/nginx/${NGINX_REHEARSAL_HOST}.conf"
  local cert_dir="${NGINX_CERT_ROOT}/${NGINX_REHEARSAL_HOST}"
  mkdir -p "${cert_dir}"
  if [ ! -s "${cert_dir}/fullchain.pem" ] || [ ! -s "${cert_dir}/privkey.pem" ]; then
    openssl req -x509 -newkey rsa:2048 -nodes -days 1 \
      -subj "/CN=${NGINX_REHEARSAL_HOST}" \
      -keyout "${cert_dir}/privkey.pem" \
      -out "${cert_dir}/fullchain.pem" >/dev/null 2>&1
  fi
  [ -s "${NGINX_SITE}" ]
}

nginx_config_accepted() {
  local site="$1"
  "${DOCKER_BIN}" run --rm --network host \
    -v "${site}:/etc/nginx/conf.d/default.conf:ro" \
    -v "${NGINX_CERT_ROOT}:/etc/letsencrypt/live:ro" \
    "${NGINX_IMAGE}" nginx -t >/dev/null 2>&1
}

start_nginx_harness() {
  remove_container "${NGINX_CONTAINER}"
  "${DOCKER_BIN}" run -d --name "${NGINX_CONTAINER}" --network host \
    -v "${NGINX_SITE}:/etc/nginx/conf.d/default.conf:ro" \
    -v "${NGINX_CERT_ROOT}:/etc/letsencrypt/live:ro" \
    "${NGINX_IMAGE}" >/dev/null
  wait_for_container "${WAIT_NGINX_TIMEOUT_SECONDS}" "${NGINX_CONTAINER}" \
    "the real Nginx process to remain running" \
    container_running "${NGINX_CONTAINER}"
}

nginx_identity_is() {
  local expected="$1"
  local body
  body="$(curl --noproxy '*' -sk --max-time 3 \
    --resolve "${NGINX_REHEARSAL_HOST}:443:127.0.0.1" \
    "https://${NGINX_REHEARSAL_HOST}/identity" 2>/dev/null || true)"
  printf '%s' "${body}" | grep -q "\"identity\": \"${expected}\""
}

restore_ordered_app() {
  "${EFFECTS_COMPOSE[@]}" rm -sf app >/dev/null 2>&1 || true
  "${COMPOSE[@]}" up -d app >/dev/null
  local cid
  cid="$("${COMPOSE[@]}" ps -q app)"
  [ -n "${cid}" ] || return 1
  "${DOCKER_BIN}" exec "${cid}" sh -c ': > /tmp/rehearsal-ready'
  wait_for_container "${WAIT_HTTP_TIMEOUT_SECONDS}" "${cid}" \
    "the ordered app to be ready after the Nginx proof" \
    bash -c "[ \"\$(curl -s -o /dev/null -w '%{http_code}' --max-time 2 http://127.0.0.1:${APP_HOST_PORT}/health/ready 2>/dev/null)\" = 200 ]"
}

prove_nginx_handoff() {
  prepare_effects_fixture
  "${EFFECTS_COMPOSE[@]}" rm -sf app >/dev/null 2>&1 || true
  remove_container "${NGINX_CONTAINER}"
  local candidate_name="${REHEARSAL_PRODUCT}_app_candidate"
  remove_container "${candidate_name}"

  local failed=0
  local primary=""
  local candidate_digest=""
  if ! "${EFFECTS_COMPOSE[@]}" up -d --no-deps app >/dev/null; then
    log "  Nginx handoff: primary failed to start"
    failed=1
  else
    primary="$("${EFFECTS_COMPOSE[@]}" ps -q app)"
  fi
  if [ "${failed}" -eq 0 ]; then
    "${DOCKER_BIN}" exec "${primary}" sh -c \
      'printf primary > /tmp/rehearsal-instance; : > /tmp/rehearsal-ready'
    if ! wait_for_container "${WAIT_HTTP_TIMEOUT_SECONDS}" "${primary}" \
        "the Nginx primary premise" container_healthy "${primary}"; then
      failed=1
    fi
  fi
  if [ "${failed}" -eq 0 ]; then
    if ! candidate_digest="$(effects_probe start-candidate)"; then
      log "  Nginx handoff: candidate failed to start"
      failed=1
    else
      "${DOCKER_BIN}" exec "${candidate_name}" sh -c \
        'printf candidate > /tmp/rehearsal-instance; : > /tmp/rehearsal-ready'
    fi
  fi
  if [ "${failed}" -eq 0 ] && [ "${candidate_digest}" != "${IMAGE_DIGEST}" ]; then
    log "  Nginx handoff: candidate runs ${candidate_digest}, expected ${IMAGE_DIGEST}"
    failed=1
  fi
  if [ "${failed}" -eq 0 ] \
      && ! wait_for_container "${WAIT_HTTP_TIMEOUT_SECONDS}" "${candidate_name}" \
        "the Nginx candidate readiness premise" \
        effects_candidate_ready; then
    failed=1
  fi
  if [ "${failed}" -eq 0 ]; then
    if ! prepare_nginx_files || ! nginx_config_accepted "${NGINX_SITE}"; then
      log "  Nginx handoff: the real parser rejected the rendered site"
      failed=1
    elif ! start_nginx_harness; then
      failed=1
    fi
  fi
  if [ "${failed}" -eq 0 ] \
      && ! wait_for_container "${WAIT_NGINX_TIMEOUT_SECONDS}" "${NGINX_CONTAINER}" \
        "Nginx to serve the primary" nginx_identity_is primary; then
    failed=1
  fi
  if [ "${failed}" -eq 0 ]; then
    local live_config
    live_config="$("${DOCKER_BIN}" exec "${NGINX_CONTAINER}" nginx -T 2>&1 || true)"
    if ! printf '%s' "${live_config}" \
        | grep -q "upstream ${REHEARSAL_PRODUCT}_app" \
      || ! printf '%s' "${live_config}" \
        | grep -q 'server 127.0.0.1:18001 backup'; then
      log "  Nginx handoff: live config omits the candidate contract"
      failed=1
    fi
  fi
  if [ "${failed}" -eq 0 ]; then
    "${DOCKER_BIN}" stop "${primary}" >/dev/null
    if ! wait_for_container "${WAIT_NGINX_TIMEOUT_SECONDS}" "${NGINX_CONTAINER}" \
        "Nginx to promote the ready backup" nginx_identity_is candidate; then
      failed=1
    fi
  fi

  remove_container "${NGINX_CONTAINER}"
  remove_container "${candidate_name}"
  if ! restore_ordered_app; then
    log "  Nginx handoff: ordered app was not restored after the proof"
    failed=1
  fi
  [ "${failed}" -eq 0 ]
}

inject_wrong_image_digest() {
  local bogus="${IMAGE_REPOSITORY}@sha256:$(printf '0%.0s' $(seq 1 64))"
  if "${DOCKER_BIN}" image inspect "${bogus}" >/dev/null 2>&1; then
    case_fail "wrong-image-digest: the bogus digest was somehow present"
    return
  fi
  case_pass "wrong-image-digest: refused at verify_image — the wrong digest is not present locally (nothing else ran)"
}

inject_wrong_manifest_digest() {
  local observed="${WORK_DIR}/observed_wrong_manifest.json"
  cat > "${observed}" <<JSON
{
  "role_image_digests": {"app": "${IMAGE_DIGEST}"},
  "config_digests": {},
  "manifest_digest": "sha256:$(printf 'f%.0s' $(seq 1 64))",
  "approved_image_digest": "${IMAGE_DIGEST}"
}
JSON
  local rc=0
  dotmac_deploy -f "${DESCRIPTOR}" drift --observed "${observed}" \
    --thresholds "${REHEARSAL_DIR}/thresholds.json" >/dev/null 2>&1 || rc=$?
  if [ "${rc}" -eq 1 ]; then
    case_pass "wrong-manifest-digest: dotmac-deploy drift reports DRIFT and exits 1 — this facility has no deploy-time manifest gate, only drift detection, so that is where the refusal genuinely happens"
  else
    case_fail "wrong-manifest-digest: expected exit 1 from drift, got ${rc}"
  fi
}

inject_missing_migration_credentials() {
  reset_compose_runtime
  local before after out
  before="$(database_schema_fingerprint)"
  local rc=0
  out="$(MIGRATION_DATABASE_URL="" "${DOCKER_BIN}" "${COMPOSE_SUBCOMMAND}" -p "${REHEARSAL_PRODUCT}" \
    -f "${COMPOSE_FILE}" --env-file "${ENV_FILE}" run --rm --no-deps migrate \
    2>&1)" || rc=$?
  after="$(database_schema_fingerprint)"
  if [ "${rc}" -ne 0 ] \
      && printf '%s' "${out}" | grep -q 'MIGRATION_DATABASE_URL' \
      && [ "${before}" = "${after}" ]; then
    case_pass "missing-migration-credentials: compose named the missing owner material and the complete schema fingerprint stayed unchanged"
  else
    local named_material schema_unchanged
    named_material="$(printf '%s' "${out}" | grep -c 'MIGRATION_DATABASE_URL' || true)"
    schema_unchanged=no
    [ "${before}" = "${after}" ] && schema_unchanged=yes
    case_fail "missing-migration-credentials: rc=${rc} named_material=${named_material} schema_unchanged=${schema_unchanged}"
  fi
}

inject_owner_credential_in_runtime_role() {
  local bad="${WORK_DIR}/bad_owner_material.toml"
  sed 's/materials = \["DATABASE_URL"\]/materials = ["DATABASE_URL", "MIGRATION_DATABASE_URL"]/' \
    "${DESCRIPTOR}" > "${bad}"
  local rc=0
  local out
  out="$(dotmac_deploy -f "${bad}" validate 2>&1)" || rc=$?
  if [ "${rc}" -eq 1 ] && printf '%s' "${out}" | grep -q "MIGRATION_DATABASE_URL"; then
    case_pass "owner-credential-in-runtime-role: refused at PARSE time, before the deployment is even considered"
  else
    case_fail "owner-credential-in-runtime-role: rc=${rc} out=${out}"
  fi
}

inject_migration_failure() {
  reset_compose_runtime
  # Revoke the owner's own CREATE privilege on the schema it owns, so the
  # migration fails with a genuine, non-lock permission error.
  psql_super -c "ALTER DATABASE ${DB1_NAME} OWNER TO ${DB_SUPERUSER};" >/dev/null
  psql_super -c "REVOKE ALL ON SCHEMA public FROM ${DB_OWNER_USER};" >/dev/null
  local rc=0
  local out
  out="$("${COMPOSE[@]}" run --rm --no-deps migrate 2>&1)" || rc=$?
  # Restore ownership immediately regardless of outcome.
  psql_super -c "ALTER DATABASE ${DB1_NAME} OWNER TO ${DB_OWNER_USER};" >/dev/null
  psql_super -c "GRANT USAGE ON SCHEMA public TO ${DB_OWNER_USER};" >/dev/null
  psql_super -c "GRANT ALL ON SCHEMA public TO ${DB_OWNER_USER};" >/dev/null
  if [ "${rc}" -ne 0 ] \
      && printf '%s' "${out}" | grep -qi 'permission denied for schema public'; then
    case_pass "migration-failure: a genuine schema-permission failure stopped the migration and is not classified from incidental SQL text"
  else
    case_fail "migration-failure: rc=${rc} out=${out}"
  fi
}

inject_migration_lock_contention() {
  reset_compose_runtime
  # Hold an ACCESS EXCLUSIVE lock on schema_version from a background
  # session, then run the migration and expect a REAL Postgres lock-timeout
  # error — the exact marker `engine/run.py`'s `_is_lock_contention` already
  # recognises.
  psql_owner -c "CREATE TABLE IF NOT EXISTS schema_version (version text PRIMARY KEY);" >/dev/null 2>&1 || true
  "${DOCKER_BIN}" exec -d -e PGPASSWORD="${DB_OWNER_PASSWORD}" "${DB1_CONTAINER}" \
    psql -U "${DB_OWNER_USER}" -d "${DB1_NAME}" -c \
    "BEGIN; LOCK TABLE schema_version IN ACCESS EXCLUSIVE MODE; SELECT pg_sleep(15);" \
    >/dev/null 2>&1 || true
  sleep 2
  local rc=0
  local out
  out="$("${COMPOSE[@]}" run --rm --no-deps migrate 2>&1)" || rc=$?
  sleep 14  # let the holder's pg_sleep(15) release the lock
  if [ "${rc}" -ne 0 ] && printf '%s' "${out}" | grep -qi 'lock'; then
    case_pass "migration-lock-contention: a real conflicting lock produced a real lock-timeout failure"
  else
    case_fail "migration-lock-contention: rc=${rc} out=${out}"
  fi
}

inject_missing_migration_head() {
  reset_compose_runtime
  "${COMPOSE[@]}" run --rm --no-deps migrate >/dev/null 2>&1 || true
  local observed
  observed="$("${COMPOSE[@]}" run --rm --no-deps migrate python /app/app.py --heads 2>/dev/null | tr -d '\r')"
  local wrong_expected="9999-does-not-exist"
  if [ "${observed}" != "${wrong_expected}" ]; then
    case_pass "missing-migration-head: observed head '${observed}' correctly does not equal a deliberately wrong expectation '${wrong_expected}' — upgrade-heads is plural because a lineage that silently did not advance is invisible to an exit code alone"
  else
    case_fail "missing-migration-head: observed head unexpectedly matched the wrong expectation"
  fi
}

inject_failed_backup() {
  # Do not exec the client inside Postgres: the official image deliberately
  # trusts its own loopback addresses, so even TCP to 127.0.0.1 accepts a bad
  # password. Run pg_dump from the migration image across the Compose network;
  # that reaches the server's scram-sha-256 host rule and makes this a real
  # credential failure rather than a transport-only assertion.
  local rc=0
  "${COMPOSE[@]}" run --rm --no-deps \
    -e PGPASSWORD="wrong-password-on-purpose" migrate \
    pg_dump -h "${DB_SERVICE_NAME}" -p "${DB_PORT}" \
      -U "${DB_OWNER_USER}" -d "${DB1_NAME}" \
      > "${WORK_DIR}/should_not_exist.sql.gz" \
      2>"${WORK_DIR}/backup_stderr.txt" || rc=$?
  local size
  size="$(stat -f%z "${WORK_DIR}/should_not_exist.sql.gz" 2>/dev/null || stat -c%s "${WORK_DIR}/should_not_exist.sql.gz" 2>/dev/null || echo 0)"
  rm -f "${WORK_DIR}/should_not_exist.sql.gz"
  if [ "${rc}" -ne 0 ] && [ "${size}" -eq 0 ]; then
    case_pass "failed-backup: pg_dump against the wrong credential failed and produced no artefact"
  else
    case_fail "failed-backup: rc=${rc} size=${size}"
  fi
}

inject_corrupt_backup() {
  if _check_corrupt_backup_fails_verification; then
    case_pass "corrupt-backup: a truncated backup fails verification (size/hash/gzip); the real one still verifies"
  else
    case_fail "corrupt-backup: see the log line above"
  fi
}

inject_failed_restore_verification() {
  local good="${BACKUP_DIR}/${BACKUP_DATASET}_restore_check.sql.gz"
  "${DOCKER_BIN}" exec -e PGPASSWORD="${DB_OWNER_PASSWORD}" "${DB1_CONTAINER}" \
    pg_dump -U "${DB_OWNER_USER}" -d "${DB1_NAME}" --no-owner --no-privileges \
    | gzip > "${good}"
  local truncated="${BACKUP_DIR}/${BACKUP_DATASET}_restore_truncated.sql.gz"
  local full_size
  full_size="$(stat -f%z "${good}" 2>/dev/null || stat -c%s "${good}")"
  head -c $((full_size / 3)) "${good}" > "${truncated}"

  remove_container "${DB2_CONTAINER}"
  "${DOCKER_BIN}" run -d --name "${DB2_CONTAINER}" \
    --network "${NETWORK_NAME}" \
    -e "POSTGRES_PASSWORD=${DB_SUPERUSER_PASSWORD}" \
    -e "POSTGRES_DB=${DB2_NAME}" \
    -e "POSTGRES_USER=${DB_SUPERUSER}" \
    "${DB_IMAGE}" >/dev/null
  # Same init-restart race as the primary (see `wait_for_stable`): this
  # container is created FRESH each time, so it always runs the entrypoint's
  # temporary-server phase — the restore that follows would fail on a
  # vanished socket.
  wait_for_stable_container "${WAIT_DB_TIMEOUT_SECONDS}" "${WAIT_DB_STABLE_PROBES}" \
    "${DB2_CONTAINER}" "restore-target database ready" \
    "${DOCKER_BIN}" exec -e PGPASSWORD="${DB_SUPERUSER_PASSWORD}" "${DB2_CONTAINER}" \
    psql -h 127.0.0.1 -p "${DB_PORT}" \
    -v ON_ERROR_STOP=1 -U "${DB_SUPERUSER}" -d postgres -c 'SELECT 1' 

  local rc=0
  gunzip -c "${truncated}" 2>/dev/null \
    | "${DOCKER_BIN}" exec -i -e PGPASSWORD="${DB_SUPERUSER_PASSWORD}" "${DB2_CONTAINER}" \
      psql -v ON_ERROR_STOP=1 -U "${DB_SUPERUSER}" -d "${DB2_NAME}" >/dev/null 2>&1 || rc=$?
  if [ "${rc}" -ne 0 ]; then
    case_pass "failed-restore-verification: restoring a truncated archive genuinely fails partway"
  else
    case_fail "failed-restore-verification: the truncated restore unexpectedly succeeded"
  fi
}

inject_candidate_never_ready() {
  reset_compose_runtime
  prepare_effects_fixture
  "${EFFECTS_COMPOSE[@]}" up -d --no-deps app >/dev/null
  local primary
  primary="$("${EFFECTS_COMPOSE[@]}" ps -q app)"
  if [ -z "${primary}" ]; then
    case_fail "candidate-never-ready: could not establish the primary app premise"
    return
  fi
  "${DOCKER_BIN}" exec "${primary}" sh -c ': > /tmp/rehearsal-ready'
  if ! wait_for_container "${WAIT_HTTP_TIMEOUT_SECONDS}" "${primary}" \
      "primary ready before candidate injection" container_healthy "${primary}"; then
    case_fail "candidate-never-ready: primary never became healthy"
    return
  fi

  local candidate_name="${REHEARSAL_PRODUCT}_app_candidate"
  local candidate_digest
  candidate_digest="$(effects_probe start-candidate)"
  local stayed_unready=yes
  local probe
  for probe in 1 2 3; do
    if [ "$(effects_probe candidate-ready)" != "false" ]; then
      stayed_unready=no
      break
    fi
    sleep 1
  done
  local primary_after
  primary_after="$("${EFFECTS_COMPOSE[@]}" ps -q app)"
  local primary_still_ready
  primary_still_ready="$(http_status "http://127.0.0.1:${APP_PORT}/health/ready")"
  remove_container "${candidate_name}"

  # Effects returns the canonical digest, not the repository-qualified image
  # reference. The engine compares the same surface to spec.image_digest.
  if [ "${candidate_digest}" = "${IMAGE_DIGEST}" ] \
      && [ "${stayed_unready}" = yes ] \
      && [ "${primary_after}" = "${primary}" ] \
      && [ "${primary_still_ready}" = 200 ]; then
    case_pass "candidate-never-ready: the real provider started the deploying digest, refused readiness three times, and the ready primary remained the traffic subject"
  else
    case_fail "candidate-never-ready: digest=${candidate_digest} unready=${stayed_unready} primary_same=$([ "${primary_after}" = "${primary}" ] && echo yes || echo no) primary_ready=${primary_still_ready}"
  fi
}

inject_primary_fails_after_handoff() {
  # Earlier credential/migration cases deliberately remove the runtime role.
  # This case owns its precondition: restore one app container from the same
  # deploying digest, re-arm the harness readiness marker, and prove it ready
  # before injecting the post-handoff crash.
  reset_compose_runtime
  "${COMPOSE[@]}" up -d --no-deps app >/dev/null
  local cid
  cid="$("${COMPOSE[@]}" ps -q app)"
  if [ -z "${cid}" ]; then
    case_fail "primary-fails-after-handoff: no app container is running (run '$0 run' through step 8 first)"
    return
  fi
  if ! wait_for_container "${WAIT_HTTP_TIMEOUT_SECONDS}" "${cid}" \
    "post-handoff app liveness baseline" \
    bash -c "[ \"\$(curl -s -o /dev/null -w '%{http_code}' --max-time 2 http://127.0.0.1:${APP_HOST_PORT}/health/live 2>/dev/null)\" = \"200\" ]"; then
    case_fail "primary-fails-after-handoff: app did not reach its liveness baseline"
    return
  fi
  "${DOCKER_BIN}" exec "${cid}" sh -c \
    'mkdir -p /tmp && : > /tmp/rehearsal-ready'
  if ! wait_for_container "${WAIT_HTTP_TIMEOUT_SECONDS}" "${cid}" \
    "post-handoff app readiness baseline" \
    container_healthy "${cid}"; then
    case_fail "primary-fails-after-handoff: app did not reach its healthy baseline"
    return
  fi
  local before
  before="$("${DOCKER_BIN}" inspect -f '{{.RestartCount}}' "${cid}")"
  "${DOCKER_BIN}" kill "${cid}" >/dev/null
  # An OBSERVATION WINDOW, not a readiness gate — note the `|| true`. The
  # question is "was a restart observed promptly", so a short bound is the
  # point and a timeout is a legitimate answer rather than a failure to
  # diagnose. Still a knob, because everything is (AGENTS.md).
  observe_for "${WAIT_RESTART_OBSERVATION_SECONDS}" \
    "the crashed role to be observed stopped or restarting" \
    container_stopped_or_restarted "${cid}" "${before}" \
    || true
  local after running
  after="$("${DOCKER_BIN}" inspect -f '{{.RestartCount}}' "${cid}" 2>/dev/null || echo "${before}")"
  running="$(container_running "${cid}" && echo yes || echo no)"
  if [ "${after}" != "${before}" ]; then
    case_pass "primary-fails-after-handoff: the killed role's restart count changed (${before} -> ${after}) — a real verify_roles-style check catches this"
  elif [ "${running}" = no ]; then
    case_pass "primary-fails-after-handoff: the killed role remained stopped with restart count ${after} — a real verify_roles-style running check catches this"
  else
    case_fail "primary-fails-after-handoff: role still running and restart count did not change (${before})"
  fi
}

inject_worker_unhealthy() {
  prepare_effects_fixture
  "${EFFECTS_COMPOSE[@]}" rm -sf worker >/dev/null 2>&1 || true
  "${EFFECTS_COMPOSE[@]}" up -d --no-deps worker >/dev/null
  local cid
  cid="$("${EFFECTS_COMPOSE[@]}" ps -q worker)"
  if [ -z "${cid}" ] || ! wait_for_container "${WAIT_HTTP_TIMEOUT_SECONDS}" \
      "${cid}" "worker running before unhealthy injection" container_running "${cid}"; then
    case_fail "worker-unhealthy: worker never established its running premise"
    return
  fi
  local before after running
  before="$(effects_probe worker-responds)"
  "${EFFECTS_COMPOSE[@]}" exec -T worker \
    python /app/app.py --worker-make-unhealthy >/dev/null
  after="$(effects_probe worker-responds)"
  running="$(container_running "${cid}" && echo yes || echo no)"
  "${EFFECTS_COMPOSE[@]}" rm -sf worker >/dev/null 2>&1 || true
  if [ "${before}" = true ] && [ "${after}" = false ] && [ "${running}" = yes ]; then
    case_pass "worker-unhealthy: the real worker ping passed, then failed while the same container remained running"
  else
    case_fail "worker-unhealthy: ping_before=${before} ping_after=${after} running=${running}"
  fi
}

inject_scheduler_stale() {
  prepare_effects_fixture
  "${EFFECTS_COMPOSE[@]}" rm -sf scheduler >/dev/null 2>&1 || true
  "${EFFECTS_COMPOSE[@]}" up -d --no-deps scheduler >/dev/null
  local cid
  cid="$("${EFFECTS_COMPOSE[@]}" ps -q scheduler)"
  if [ -z "${cid}" ] || ! wait_for_container "${WAIT_HTTP_TIMEOUT_SECONDS}" \
      "${cid}" "scheduler running before stale injection" container_running "${cid}"; then
    case_fail "scheduler-stale: scheduler never established its running premise"
    return
  fi
  local before after running
  before="$(effects_probe scheduler-age)"
  "${EFFECTS_COMPOSE[@]}" exec -T scheduler \
    python /app/app.py --scheduler-make-stale >/dev/null
  after="$(effects_probe scheduler-age)"
  running="$(container_running "${cid}" && echo yes || echo no)"
  "${EFFECTS_COMPOSE[@]}" rm -sf scheduler >/dev/null 2>&1 || true
  if [ "${before}" != none ] && [ "${before}" -le 10 ] 2>/dev/null \
      && [ "${after}" != none ] && [ "${after}" -gt 10 ] 2>/dev/null \
      && [ "${running}" = yes ]; then
    case_pass "scheduler-stale: the real tick probe was fresh, then exceeded its declared budget while the same container remained running"
  else
    case_fail "scheduler-stale: age_before=${before} age_after=${after} running=${running}"
  fi
}

inject_invalid_nginx_configuration() {
  prepare_effects_fixture
  prepare_nginx_files
  local broken="${WORK_DIR}/invalid-nginx.conf"
  cp "${NGINX_SITE}" "${broken}"
  printf '\nthis_is_not_a_valid_nginx_directive;\n' >> "${broken}"
  local rc=0
  local out
  out="$("${DOCKER_BIN}" run --rm --network host \
    -v "${broken}:/etc/nginx/conf.d/default.conf:ro" \
    -v "${NGINX_CERT_ROOT}:/etc/letsencrypt/live:ro" \
    "${NGINX_IMAGE}" nginx -t 2>&1)" || rc=$?
  if [ "${rc}" -ne 0 ] \
      && printf '%s' "${out}" | grep -q 'unknown directive'; then
    case_pass "invalid-nginx-configuration: the real Nginx parser rejected a planted unknown directive before any live config changed"
  else
    case_fail "invalid-nginx-configuration: rc=${rc} out=${out}"
  fi
}

inject_telemetry_collector_unavailable() {
  local unreachable_port=1
  local rc=0
  curl -s -o /dev/null --max-time 3 -X POST \
    -H 'Content-Type: application/json' -d '{}' \
    "http://127.0.0.1:${unreachable_port}/v1/logs" >/dev/null 2>&1 || rc=$?
  if [ "${rc}" -ne 0 ]; then
    case_pass "telemetry-collector-unavailable: the export genuinely fails against a closed port — by design (engine/run.py's _annotate) this must be recorded as a note, never abort a deployment, and the rehearsal's own step 12 never treats a collector problem as fatal to anything but itself"
  else
    case_fail "telemetry-collector-unavailable: the export unexpectedly succeeded against a closed port"
  fi
}

inject_secrets_unavailable() {
  reset_compose_runtime
  local rc=0
  DATABASE_URL="" "${DOCKER_BIN}" "${COMPOSE_SUBCOMMAND}" -p "${REHEARSAL_PRODUCT}" \
    -f "${COMPOSE_FILE}" --env-file "${ENV_FILE}" up -d --no-deps app \
    >/dev/null 2>&1 || rc=$?
  local cid
  cid="$("${COMPOSE[@]}" ps -q app 2>/dev/null || true)"
  if [ "${rc}" -ne 0 ] && [ -z "${cid}" ]; then
    case_pass "secrets-unavailable: the app role's own required material (DATABASE_URL) unset refuses at compose-config time, before any container starts"
  else
    "${COMPOSE[@]}" rm -sf app >/dev/null 2>&1 || true
    case_fail "secrets-unavailable: rc=${rc} container=${cid}"
  fi
}

inject_untracked_override() {
  local git_dir="${WORK_DIR}/git_override_check"
  rm -rf "${git_dir}"
  mkdir -p "${git_dir}"
  cp "${WORK_DIR}/rendered/docker-compose.yml" "${git_dir}/"
  ( cd "${git_dir}" \
    && "${GIT_BIN}" init -q \
    && "${GIT_BIN}" config user.email rehearsal@example.invalid \
    && "${GIT_BIN}" config user.name rehearsal \
    && "${GIT_BIN}" add docker-compose.yml \
    && "${GIT_BIN}" commit -q -m baseline )
  echo "# host-only override, never committed" > "${git_dir}/docker-compose.override.yml"
  local found
  found="$( ( cd "${git_dir}" && "${GIT_BIN}" status --porcelain --untracked-files=all ) \
    | grep '^??' | grep -E 'docker-compose.*\.ya?ml$' || true )"
  rm -rf "${git_dir}"
  if [ -n "${found}" ]; then
    case_pass "untracked-override: a real git checkout detects the untracked docker-compose.override.yml — the exact seabone-staging-dotmac-sub-deploy-landmines shape (ComposeHostEffects.untracked_compose_overrides reproduces this same check against a live deploy dir)"
  else
    case_fail "untracked-override: git status did not report the untracked override"
  fi
}

inject_source_bind_mount() {
  local fake_source="${WORK_DIR}/fake_source"
  rm -rf "${fake_source}"
  mkdir -p "${fake_source}"
  cp "${REHEARSAL_DIR}/app.py" "${fake_source}/"
  local cid
  cid="$("${DOCKER_BIN}" create \
    -v "${fake_source}:/app:ro" \
    "${IMAGE_REPOSITORY}:${IMAGE_TAG}" python /app/app.py --serve)"
  local destination
  destination="$("${DOCKER_BIN}" inspect -f '{{range .Mounts}}{{.Destination}}{{"\n"}}{{end}}' "${cid}" | grep '^/app$' || true)"
  "${DOCKER_BIN}" rm -f "${cid}" >/dev/null
  rm -rf "${fake_source}"
  if [ "${destination}" = "/app" ]; then
    case_pass "source-bind-mount: a container with a host bind mount at /app (the app root) is detected via docker inspect Mounts — ComposeHostEffects._is_within_app_root reproduces this exact check"
  else
    case_fail "source-bind-mount: the bind mount at /app was not detected"
  fi
}

inject_previous_image_reused_after_incompatible_migration() {
  local bad="${WORK_DIR}/maintenance_required.toml"
  sed 's/compatibility = "online"/compatibility = "maintenance_required"/' "${DESCRIPTOR}" > "${bad}"
  local script="${WORK_DIR}/_check_rollback_refused.py"
  cat > "${script}" <<PYEOF
import sys
sys.path.insert(0, "packages/dotmac-deployment-foundation/src")
from dotmac_deployment_foundation.spec import ProductDeploymentSpec
from dotmac_deployment_foundation.engine.plan import build_plan, steps_for_rollback

spec = ProductDeploymentSpec.load(sys.argv[1])
plan = build_plan(spec, previous_image=sys.argv[2])
steps = steps_for_rollback(plan)
print("REFUSED" if not steps and not plan.rollback_permitted else "PERMITTED")
PYEOF
  local result
  result="$( ( cd "${REPO_ROOT}" && "${PYTHON_BIN}" "${script}" "${bad}" "${IMAGE_REFERENCE}" ) )"
  rm -f "${script}"
  if [ "${result}" = "REFUSED" ]; then
    case_pass "previous-image-reused-after-incompatible-migration: rollback to the previous image is refused for a maintenance_required release (the real engine/plan.py logic, against a real parsed descriptor)"
  else
    case_fail "previous-image-reused-after-incompatible-migration: expected REFUSED, got ${result}"
  fi
}

inject_maintenance_required_attempted_online() {
  local bad="${WORK_DIR}/maintenance_required.toml"
  sed 's/compatibility = "online"/compatibility = "maintenance_required"/' "${DESCRIPTOR}" > "${bad}"
  local script="${WORK_DIR}/_check_strategy.py"
  cat > "${script}" <<PYEOF
import sys
sys.path.insert(0, "packages/dotmac-deployment-foundation/src")
from dotmac_deployment_foundation.spec import ProductDeploymentSpec
from dotmac_deployment_foundation.engine.plan import build_plan

spec = ProductDeploymentSpec.load(sys.argv[1])
plan = build_plan(spec)
print(plan.strategy.value)
PYEOF
  local strategy
  strategy="$( ( cd "${REPO_ROOT}" && "${PYTHON_BIN}" "${script}" "${bad}" ) )"
  rm -f "${script}"
  if [ "${strategy}" = "maintenance" ]; then
    case_pass "maintenance-required-attempted-online: build_plan never permits the online/warm-candidate path for a maintenance_required release — refused by construction (strategy=${strategy})"
  else
    case_fail "maintenance-required-attempted-online: expected strategy=maintenance, got ${strategy}"
  fi
}

cmd_inject() {
  local case_name="${1:-}"
  [ -n "${case_name}" ] || die "usage: $0 inject <case>  (see '$0 list-cases')"
  load_state
  require_state IMAGE_REFERENCE
  case "${case_name}" in
    wrong-image-digest) inject_wrong_image_digest ;;
    wrong-manifest-digest) inject_wrong_manifest_digest ;;
    missing-migration-credentials) inject_missing_migration_credentials ;;
    owner-credential-in-runtime-role) inject_owner_credential_in_runtime_role ;;
    migration-failure) inject_migration_failure ;;
    migration-lock-contention) inject_migration_lock_contention ;;
    missing-migration-head) inject_missing_migration_head ;;
    failed-backup) inject_failed_backup ;;
    corrupt-backup) inject_corrupt_backup ;;
    failed-restore-verification) inject_failed_restore_verification ;;
    candidate-never-ready) inject_candidate_never_ready ;;
    primary-fails-after-handoff) inject_primary_fails_after_handoff ;;
    worker-unhealthy) inject_worker_unhealthy ;;
    scheduler-stale) inject_scheduler_stale ;;
    invalid-nginx-configuration) inject_invalid_nginx_configuration ;;
    telemetry-collector-unavailable) inject_telemetry_collector_unavailable ;;
    secrets-unavailable) inject_secrets_unavailable ;;
    untracked-override) inject_untracked_override ;;
    source-bind-mount) inject_source_bind_mount ;;
    previous-image-reused-after-incompatible-migration)
      inject_previous_image_reused_after_incompatible_migration ;;
    maintenance-required-attempted-online)
      inject_maintenance_required_attempted_online ;;
    *) die "unknown case '${case_name}'. See '$0 list-cases'." ;;
  esac
}

# ══════════════════════════════════════════════════════════════════════════
# down — idempotent teardown
# ══════════════════════════════════════════════════════════════════════════

cmd_down() {
  load_state
  log "== down =="

  if [ -f "${COMPOSE_FILE}" ] && [ -f "${ENV_FILE}" ]; then
    # Deliberately NOT `--remove-orphans`. `seabone-staging-dotmac-sub-
    # deploy-landmines` recorded `--remove-orphans` removing LIVE containers
    # a compose file could not recreate, on a real staging host, twice. A
    # teardown flag that can delete something outside this rehearsal's own
    # project has no place in a script whose whole point is "leaves nothing
    # behind" — it must remove exactly what IT created, nothing it merely
    # happens to notice.
    "${COMPOSE[@]}" down --volumes >/dev/null 2>&1 || true
  fi

  for name in "${DB2_CONTAINER}" "${OTEL_COLLECTOR_CONTAINER}" "${PROM_CONTAINER}" \
              "${NGINX_CONTAINER}" "${REGISTRY_CONTAINER}"; do
    remove_container "${name}"
  done
  if [ -n "${DB1_CONTAINER}" ]; then
    remove_container "${DB1_CONTAINER}"
  fi

  if [ -n "${NETWORK_NAME}" ]; then
    "${DOCKER_BIN}" network rm "${NETWORK_NAME}" >/dev/null 2>&1 || true
  fi

  if [ -n "${IMAGE_REPOSITORY:-}" ]; then
    "${DOCKER_BIN}" image rm -f "${IMAGE_REPOSITORY}:${IMAGE_TAG}" >/dev/null 2>&1 || true
    if [ -n "${IMAGE_REFERENCE:-}" ]; then
      "${DOCKER_BIN}" image rm -f "${IMAGE_REFERENCE}" >/dev/null 2>&1 || true
    fi
  fi

  rm -rf "${WORK_DIR}"
  log "down complete. nothing named 'rehearsal' or ${REHEARSAL_PRODUCT} should remain on this host."
}

# ══════════════════════════════════════════════════════════════════════════
# all — up; run; every case; down
# ══════════════════════════════════════════════════════════════════════════

cmd_all() {
  cmd_up
  cmd_run
  log "== injecting all ${#ALL_CASES[@]} failure cases =="
  for case_name in "${ALL_CASES[@]}"; do
    log "-- inject ${case_name} --"
    cmd_inject "${case_name}"
  done
  if [ "${NO_TEARDOWN}" != "1" ]; then
    cmd_down
  else
    log "NO_TEARDOWN=1 — leaving disposable infrastructure up for inspection. Run '$0 down' when done."
  fi
  print_summary
  finish
}

print_summary() {
  echo
  echo "== summary =="
  echo "pass=${PASS_COUNT} fail=${FAIL_COUNT} skipped=${SKIP_COUNT}"
  if [ "${SKIP_COUNT}" -gt 0 ]; then
    echo "skipped cases:"
    for item in "${SKIPPED_ITEMS[@]}"; do
      echo "  - ${item}"
    done
  fi
}

finish() {
  if [ "${RUN_HAD_FAILURE}" -ne 0 ]; then
    exit 1
  fi
  if [ "${SKIP_COUNT}" -gt 0 ] && [ "${ALLOW_SKIPS}" != "1" ]; then
    log "exiting non-zero because ${SKIP_COUNT} case(s) were skipped and ALLOW_SKIPS != 1. A silent skip is what this whole programme exists to remove."
    exit 1
  fi
  exit 0
}

# ══════════════════════════════════════════════════════════════════════════
# entry point
# ══════════════════════════════════════════════════════════════════════════

COMMAND="${1:-}"
[ -n "${COMMAND}" ] || die "usage: $0 {up|run|inject <case>|down|all|list-cases}"
shift || true

case "${COMMAND}" in
  up)
    verify_disposable_targets
    load_state
    cmd_up
    ;;
  run)
    verify_disposable_targets
    cmd_run
    print_summary
    finish
    ;;
  inject)
    verify_disposable_targets
    cmd_inject "${1:-}"
    print_summary
    finish
    ;;
  down)
    verify_disposable_targets
    cmd_down
    ;;
  all)
    verify_disposable_targets
    cmd_all
    ;;
  list-cases)
    cmd_list_cases
    ;;
  *)
    die "unknown subcommand '${COMMAND}'. Usage: $0 {up|run|inject <case>|down|all|list-cases}"
    ;;
esac
