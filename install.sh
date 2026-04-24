#!/usr/bin/env bash
# gpsdo-monitor canonical installer.
#
# Called directly by operators, or delegated to by sigmond's catalog
# installer. Idempotent.
#
# Modes:
#   install.sh             # production install — copy pip install from
#                          #   the repo directory into system Python.
#   install.sh --dev       # development install — symlink
#                          #   /opt/git/gpsdo-monitor to this repo so
#                          #   sigmond's canonical-path logic finds it,
#                          #   and use `pip install -e` so Python edits
#                          #   take effect on `systemctl restart` with
#                          #   no re-install. See README "Development
#                          #   setup".
set -euo pipefail

REPO_DIR="${REPO_DIR:-$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)}"
PREFIX="${PREFIX:-/usr/local}"
CONF_DIR="${CONF_DIR:-/etc/gpsdo-monitor}"
UDEV_DIR="${UDEV_DIR:-/etc/udev/rules.d}"
SYSTEMD_DIR="${SYSTEMD_DIR:-/etc/systemd/system}"
SYSUSERS_DIR="${SYSUSERS_DIR:-/etc/sysusers.d}"
CANONICAL_DIR="${CANONICAL_DIR:-/opt/git/gpsdo-monitor}"
SERVICE_USER="${SERVICE_USER:-gpsdo}"

DEV_MODE=false

while [[ $# -gt 0 ]]; do
    case $1 in
        --dev)  DEV_MODE=true; shift ;;
        -h|--help)
            sed -n '3,16p' "$0" | sed 's/^# \{0,1\}//'; exit 0 ;;
        *) echo "unknown flag: $1" >&2; exit 2 ;;
    esac
done

require_root() {
    if [[ $EUID -ne 0 ]]; then
        echo "error: $0 must be run as root (use sudo)" >&2
        exit 1
    fi
}

install_deps() {
    if command -v apt-get >/dev/null 2>&1; then
        apt-get install -y --no-install-recommends \
            python3 python3-pip python3-venv libhidapi-hidraw0
    else
        echo "warn: no apt-get; install Python 3.11+ and libhidapi-hidraw manually" >&2
    fi
}

install_user() {
    install -d -m 0755 "$SYSUSERS_DIR"
    install -m 0644 "$REPO_DIR/deploy/sysusers.d/gpsdo.conf" "$SYSUSERS_DIR/gpsdo.conf"
    systemd-sysusers
}

install_udev() {
    install -d -m 0755 "$UDEV_DIR"
    install -m 0644 "$REPO_DIR/deploy/99-gpsdo.rules" "$UDEV_DIR/99-gpsdo.rules"
    udevadm control --reload-rules
    udevadm trigger --attr-match=subsystem=hidraw || true
    udevadm trigger --attr-match=subsystem=tty    || true
}

install_canonical_symlink() {
    # Dev mode only. Points /opt/git/gpsdo-monitor at this checkout so
    # sigmond's deploy.toml lookup + the canonical-path convention keep
    # working without a second clone that would drift from the dev
    # tree. Refuses to clobber an existing real directory — a fresh
    # production install should remove /opt/git/gpsdo-monitor first.
    install -d -m 0755 "$(dirname "$CANONICAL_DIR")"
    if [[ -L "$CANONICAL_DIR" ]]; then
        local current target
        current="$(readlink -f "$CANONICAL_DIR")"
        target="$(readlink -f "$REPO_DIR")"
        if [[ "$current" == "$target" ]]; then
            echo "canonical symlink already points at $target"
            return
        fi
        echo "error: $CANONICAL_DIR is a symlink to $current" >&2
        echo "       remove it and re-run: sudo rm $CANONICAL_DIR" >&2
        exit 1
    fi
    if [[ -e "$CANONICAL_DIR" ]]; then
        echo "error: $CANONICAL_DIR already exists (not a symlink)" >&2
        echo "       a previous production install is there; remove it first:" >&2
        echo "       sudo rm -rf $CANONICAL_DIR" >&2
        exit 1
    fi
    ln -s "$REPO_DIR" "$CANONICAL_DIR"
    echo "linked $CANONICAL_DIR -> $REPO_DIR"
}

verify_traversable() {
    # An editable install records the repo path in a .pth file. If the
    # service user can't traverse it at runtime, systemd fails to
    # import the package even though `pip install -e` succeeded as
    # root. Catch that trap here.
    if ! id -u "$SERVICE_USER" &>/dev/null; then
        return  # sysusers step will create it; skip pre-check
    fi
    local probe="$REPO_DIR/src/gpsdo_monitor/__init__.py"
    if ! sudo -u "$SERVICE_USER" test -r "$probe"; then
        echo "error: $SERVICE_USER cannot read $probe" >&2
        echo "       one of the parent directories is not traversable" >&2
        echo "       (typically a home directory with mode 700)." >&2
        echo "" >&2
        echo "       fix: relocate the repo to /opt/git/gpsdo-monitor" >&2
        echo "            (a real clone, not a symlink) and re-run." >&2
        exit 1
    fi
}

install_python() {
    if [[ "$DEV_MODE" == "true" ]]; then
        # Editable: systemd runs code from $REPO_DIR via the .pth file
        # pip writes into site-packages. Restart-to-pick-up-edits, no
        # re-install required for pure-Python changes.
        python3 -m pip install --break-system-packages -e "$REPO_DIR"
    else
        python3 -m pip install --break-system-packages --upgrade "$REPO_DIR"
    fi
}

install_systemd() {
    install -d -m 0755 "$SYSTEMD_DIR"
    install -m 0644 "$REPO_DIR/deploy/gpsdo-monitor.service" "$SYSTEMD_DIR/gpsdo-monitor.service"
    install -d -m 0755 "$CONF_DIR"
    if [[ ! -f "$CONF_DIR/config.toml" ]]; then
        install -m 0644 "$REPO_DIR/deploy/config.example.toml" "$CONF_DIR/config.toml"
    fi
    systemctl daemon-reload
    systemctl enable gpsdo-monitor.service
    systemctl restart gpsdo-monitor.service || true
}

main() {
    require_root
    install_deps
    install_user
    install_udev
    if [[ "$DEV_MODE" == "true" ]]; then
        install_canonical_symlink
        verify_traversable
    fi
    install_python
    install_systemd
    if [[ "$DEV_MODE" == "true" ]]; then
        echo ""
        echo "gpsdo-monitor installed (dev mode)."
        echo "  canonical path: $CANONICAL_DIR -> $REPO_DIR"
        echo "  edit Python code directly in $REPO_DIR, then:"
        echo "    sudo systemctl restart gpsdo-monitor.service"
        echo ""
        echo "Status:"
    else
        echo "gpsdo-monitor installed. Status:"
    fi
    systemctl --no-pager status gpsdo-monitor.service || true
}

main "$@"
