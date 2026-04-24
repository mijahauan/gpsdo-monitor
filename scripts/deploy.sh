#!/usr/bin/env bash
# =============================================================================
# deploy.sh — pull-to-deploy refresh for gpsdo-monitor.
# =============================================================================
#
# This script does NOT install gpsdo-monitor from scratch. For first-run
# install (apt deps, gpsdo user, udev rules, systemd unit, config),
# see install.sh.
#
# What this does, and only this:
#
#   1. Refuse to run if the repo has uncommitted changes (unless
#      --force-dirty). This is the single rule that keeps production
#      from drifting away from git.
#   2. Optionally `git pull --ff-only` (--pull).
#   3. Verify the gpsdo service user can traverse the repo. An editable
#      install into a directory the service user cannot reach will
#      succeed as root but fail at systemd runtime; we catch that here
#      before pip writes a broken .pth file.
#   4. Refresh the editable install (`pip install -e .`). No-op unless
#      pyproject.toml or its deps changed; refreshes console-script
#      shims if entry points moved.
#   5. `systemctl restart gpsdo-monitor.service`.
#   6. Print the active git SHA so you can see what just deployed.
#
# This assumes the repo was originally installed in --dev mode (editable
# install + /opt/git/gpsdo-monitor symlink). For a plain copy install,
# re-running `install.sh` is the equivalent operation.
#
# Usage:
#   sudo ./scripts/deploy.sh              # check, refresh, restart
#   sudo ./scripts/deploy.sh --pull       # git pull first
#   sudo ./scripts/deploy.sh --no-restart # refresh editable install only
#   sudo ./scripts/deploy.sh --force-dirty
#   sudo ./scripts/deploy.sh --dry-run
#
# Exit codes:
#   0  success
#   1  uncommitted changes blocked the run
#   2  pip install failed or post-install import verify failed
#   3  systemctl restart failed
#   4  generic error (repo not found, service user unreachable, etc.)
# =============================================================================
set -euo pipefail

SCRIPT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
REPO_DIR="$(dirname -- "$SCRIPT_DIR")"
SERVICE_UNIT="gpsdo-monitor.service"
SERVICE_USER="${SERVICE_USER:-gpsdo}"

DO_GIT_PULL=false
FORCE_DIRTY=false
DO_RESTART=true
DRY_RUN=false

RED=$'\033[0;31m'; GREEN=$'\033[0;32m'; YELLOW=$'\033[1;33m'; BLUE=$'\033[0;34m'; NC=$'\033[0m'
log_info()  { echo "${GREEN}[INFO]${NC} $*" >&2; }
log_warn()  { echo "${YELLOW}[WARN]${NC} $*" >&2; }
log_error() { echo "${RED}[ERROR]${NC} $*" >&2; }
log_step()  { echo "" >&2; echo "${BLUE}━━━ $* ━━━${NC}" >&2; }

usage() { sed -n '2,44p' "$0" | sed 's/^# \{0,1\}//'; exit 0; }

while [[ $# -gt 0 ]]; do
    case $1 in
        --pull)          DO_GIT_PULL=true; shift ;;
        --force-dirty)   FORCE_DIRTY=true; shift ;;
        --no-restart)    DO_RESTART=false; shift ;;
        --dry-run|-n)    DRY_RUN=true; shift ;;
        -h|--help)       usage ;;
        *) log_error "unknown flag: $1"; exit 4 ;;
    esac
done

if [[ $EUID -ne 0 ]]; then
    log_error "must run as root: sudo $0"
    exit 4
fi

if [[ ! -f "$REPO_DIR/pyproject.toml" ]]; then
    log_error "not a gpsdo-monitor repo: no pyproject.toml at $REPO_DIR"
    exit 4
fi

REPO_OWNER="$(stat -c '%U' "$REPO_DIR")"

# ── 1. clean-tree guard ────────────────────────────────────────────────
log_step "verify clean working tree"
if ! sudo -u "$REPO_OWNER" git -C "$REPO_DIR" rev-parse --git-dir &>/dev/null; then
    log_error "$REPO_DIR is not a git repository"
    exit 4
fi
DIRTY="$(sudo -u "$REPO_OWNER" git -C "$REPO_DIR" status --porcelain)"
if [[ -n "$DIRTY" ]]; then
    if [[ "$FORCE_DIRTY" == "true" ]]; then
        log_warn "uncommitted changes present, proceeding (--force-dirty)"
        echo "$DIRTY" | sed 's/^/    /' >&2
    else
        log_error "uncommitted changes in $REPO_DIR — refusing to deploy."
        log_error "    commit or stash them, or pass --force-dirty."
        echo "$DIRTY" | sed 's/^/    /' >&2
        exit 1
    fi
else
    log_info "working tree is clean"
fi
OLD_SHA="$(sudo -u "$REPO_OWNER" git -C "$REPO_DIR" rev-parse --short HEAD)"
log_info "current HEAD: $OLD_SHA"

# ── 2. optional git pull ───────────────────────────────────────────────
if [[ "$DO_GIT_PULL" == "true" ]]; then
    log_step "git pull --ff-only"
    if [[ "$DRY_RUN" == "true" ]]; then
        log_info "(dry run) would: sudo -u $REPO_OWNER git -C $REPO_DIR pull --ff-only"
    else
        if ! sudo -u "$REPO_OWNER" git -C "$REPO_DIR" pull --ff-only; then
            log_error "git pull failed — resolve and rerun"
            exit 4
        fi
        NEW_SHA="$(sudo -u "$REPO_OWNER" git -C "$REPO_DIR" rev-parse --short HEAD)"
        if [[ "$OLD_SHA" == "$NEW_SHA" ]]; then
            log_info "already up to date ($NEW_SHA)"
        else
            log_info "updated $OLD_SHA → $NEW_SHA"
        fi
    fi
fi

# ── 3. service-user traversability ─────────────────────────────────────
log_step "verify $SERVICE_USER can read source tree"
if ! id -u "$SERVICE_USER" &>/dev/null; then
    log_warn "user '$SERVICE_USER' does not exist — run install.sh first"
else
    PROBE="$REPO_DIR/src/gpsdo_monitor/__init__.py"
    if ! sudo -u "$SERVICE_USER" test -r "$PROBE"; then
        log_error "$SERVICE_USER cannot read $PROBE"
        log_error ""
        log_error "the editable install will succeed here as root but the"
        log_error "daemon will fail to import at runtime, because a parent"
        log_error "directory of $REPO_DIR is not traversable by $SERVICE_USER"
        log_error "(typically a home directory with mode 700)."
        log_error ""
        log_error "fix: relocate the repo to /opt/git/gpsdo-monitor (a real"
        log_error "     clone, not a symlink) and re-run install.sh."
        exit 4
    fi
    log_info "$SERVICE_USER can read $PROBE"
fi

# ── 4. pip install -e . ────────────────────────────────────────────────
log_step "refresh editable install"
if [[ "$DRY_RUN" == "true" ]]; then
    log_info "(dry run) would: pip install -e $REPO_DIR --break-system-packages"
else
    if ! python3 -m pip install -q --break-system-packages -e "$REPO_DIR" >/dev/null 2>&1; then
        log_warn "quiet pip install failed — retrying with full output"
        if ! python3 -m pip install --break-system-packages -e "$REPO_DIR"; then
            log_error "pip install failed"
            exit 2
        fi
    fi
    RESOLVED="$(python3 -c 'import gpsdo_monitor, inspect; print(inspect.getfile(gpsdo_monitor))')"
    EXPECTED="$REPO_DIR/src/gpsdo_monitor/"
    if [[ "$RESOLVED" != "$EXPECTED"* ]]; then
        log_error "python resolves gpsdo_monitor from $RESOLVED — expected $EXPECTED*"
        log_error "editable install did not take effect; not restarting."
        exit 2
    fi
    log_info "editable install resolves to $RESOLVED"
fi

# ── 5. systemctl restart ───────────────────────────────────────────────
if [[ "$DO_RESTART" == "true" ]]; then
    log_step "restart $SERVICE_UNIT"
    if [[ "$DRY_RUN" == "true" ]]; then
        log_info "(dry run) would: systemctl restart $SERVICE_UNIT"
    elif systemctl list-unit-files --no-legend --no-pager "$SERVICE_UNIT" &>/dev/null; then
        if systemctl restart "$SERVICE_UNIT"; then
            STATE="$(systemctl is-active "$SERVICE_UNIT" 2>/dev/null || echo unknown)"
            log_info "$SERVICE_UNIT: $STATE"
        else
            log_error "$SERVICE_UNIT: restart failed"
            exit 3
        fi
    else
        log_warn "$SERVICE_UNIT not installed — run install.sh first"
    fi
else
    log_info "restart skipped (--no-restart)"
fi

# ── 6. report ──────────────────────────────────────────────────────────
log_step "summary"
FINAL_DESC="$(sudo -u "$REPO_OWNER" git -C "$REPO_DIR" log -1 --pretty=format:'%h %s')"
log_info "deployed: $FINAL_DESC"
echo "$FINAL_DESC" | awk '{print $1}'
