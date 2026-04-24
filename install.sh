#!/usr/bin/env bash
# gpsdo-monitor canonical installer.
#
# Called directly by operators, or delegated to by sigmond's catalog
# installer. Idempotent.
set -euo pipefail

REPO_DIR="${REPO_DIR:-$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)}"
PREFIX="${PREFIX:-/usr/local}"
CONF_DIR="${CONF_DIR:-/etc/gpsdo-monitor}"
UDEV_DIR="${UDEV_DIR:-/etc/udev/rules.d}"
SYSTEMD_DIR="${SYSTEMD_DIR:-/etc/systemd/system}"
SYSUSERS_DIR="${SYSUSERS_DIR:-/etc/sysusers.d}"

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

install_python() {
    python3 -m pip install --break-system-packages --upgrade "$REPO_DIR"
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
    install_python
    install_systemd
    echo "gpsdo-monitor installed. Status:"
    systemctl --no-pager status gpsdo-monitor.service || true
}

main "$@"
