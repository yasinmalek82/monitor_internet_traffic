#!/usr/bin/env bash
# Dedicated systemd installation. Existing services, firewall and system Python are untouched.
set -Eeuo pipefail
umask 022

REPO=yasinmalek82/monitor_internet_traffic
PREFIX=/opt/iran-internet-monitor
UNIT=iran-internet-monitor.service
CONFIG=/etc/iran-internet-monitor/monitor.env
UV_VERSION=0.12.1
REF=main
SOURCE=
NO_START=false
DRY_RUN=false

fail() { echo "Error: $*" >&2; exit 1; }
usage() {
    echo 'Usage: bash install.sh [--ref TAG_OR_SHA] [--source LOCAL_CHECKOUT] [--no-start] [--dry-run]'
    echo 'Ubuntu 22.04+ / Debian 12+, systemd, x86_64 or ARM64; run as root.'
}
while (($#)); do
    case "$1" in
        --ref|--source)
            (($# >= 2)) || fail "Missing value for $1"
            if [[ $1 == --ref ]]; then REF=$2; else SOURCE=$2; fi
            shift 2 ;;
        --no-start) NO_START=true; shift ;;
        --dry-run) DRY_RUN=true; shift ;;
        -h|--help) usage; exit 0 ;;
        *) usage; fail 'Unknown option' ;;
    esac
done
[[ $REF =~ ^[a-zA-Z0-9][a-zA-Z0-9._/-]*$ && $REF != *..* ]] || fail 'Invalid ref'
if "$DRY_RUN"; then
    printf 'Repository: %s\nRef: %s\nCode: %s\nConfig: %s\n' "$REPO" "$REF" "$PREFIX" "$CONFIG"
    echo 'Service: iran-internet-monitor.service, user: iran-monitor'
    echo 'Limits: MemoryHigh=128M MemoryMax=256M CPUQuota=20% Nice=10'
    echo 'One temporary chart worker; no Docker, web port or external database.'
    echo 'No commands, downloads, package installation or service changes were performed.'
    exit 0
fi
[[ $(uname -s) == Linux ]] || fail 'Linux with systemd is required'
[[ $EUID -eq 0 ]] || fail 'Run this installer as root (sudo bash install.sh)'
[[ -d /run/systemd/system ]] || fail 'A running systemd host is required; ordinary Docker containers are not supported'
[[ -r /etc/os-release ]] || fail 'Cannot identify this Linux distribution'
# shellcheck disable=SC1091
. /etc/os-release
case "$ID" in
    ubuntu) [[ ${VERSION_ID%%.*} -ge 22 ]] || fail 'Ubuntu 22.04+ required' ;;
    debian) [[ ${VERSION_ID%%.*} -ge 12 ]] || fail 'Debian 12+ required' ;;
    *) fail 'Supported distributions: Ubuntu 22.04+ and Debian 12+' ;;
esac
case "$(uname -m)" in
    x86_64)
        target=x86_64-unknown-linux-gnu
        uv_sha=90b2f223fb69d19db49e117da601f64978593417988530aa733d456141b4bcbb ;;
    aarch64|arm64)
        target=aarch64-unknown-linux-gnu
        uv_sha=769d373e146692c639b5fbaae33b331c297a32e03d30448772051902df52bbf4 ;;
    *) fail 'Supported architectures: x86_64 and ARM64' ;;
esac
for command in systemctl runuser useradd getent flock tar sha256sum; do
    command -v "$command" >/dev/null || fail "Required system command missing: $command"
done
if ! command -v curl >/dev/null || [[ ! -r /etc/ssl/certs/ca-certificates.crt ]]; then
    apt-get update -qq
    DEBIAN_FRONTEND=noninteractive apt-get install -y --no-install-recommends curl ca-certificates
fi
if [[ -e $PREFIX && ! -f $PREFIX/.managed-by-iran-monitor ]]; then
    fail "$PREFIX already exists and is not managed by this installer"
fi
[[ ! -L $PREFIX ]] || fail 'Installation prefix must not be a symlink'
if [[ -e /usr/local/bin/iran-monitor && ! -f $PREFIX/.managed-by-iran-monitor ]]; then
    fail '/usr/local/bin/iran-monitor already exists; choose a host without that conflicting command'
fi
install -d -m 0755 "$PREFIX" "$PREFIX/bin" "$PREFIX/releases"
touch "$PREFIX/.managed-by-iran-monitor"
exec 9>"$PREFIX/install.lock"
flock -n 9 || fail 'Another installer is running'
temporary=$(mktemp -d)
release=
activated=false
cleanup() {
    rm -rf "$temporary"
    if [[ -n $release ]] && ! "$activated"; then rm -rf "$release"; fi
}
trap cleanup EXIT
trap 'echo "Installation failed; existing configuration and data were preserved." >&2' ERR
download() {
    curl --fail --silent --show-error --location --retry 3 --connect-timeout 15 --max-time 240 "$1" -o "$2"
}
if [[ ! -x $PREFIX/bin/uv ]] || [[ $("$PREFIX/bin/uv" --version) != "uv $UV_VERSION"* ]]; then
    echo 'Downloading the pinned uv runtime manager...'
    download "https://github.com/astral-sh/uv/releases/download/$UV_VERSION/uv-$target.tar.gz" "$temporary/uv.tar.gz"
    printf '%s  %s\n' "$uv_sha" "$temporary/uv.tar.gz" | sha256sum -c -
    tar -xzf "$temporary/uv.tar.gz" -C "$temporary"
    install -m 0755 "$temporary/uv-$target/uv" "$PREFIX/bin/uv"
fi
if [[ -z $SOURCE ]]; then
    echo "Downloading $REPO ($REF)..."
    download "https://github.com/$REPO/archive/$REF.tar.gz" "$temporary/source.tar.gz"
    mkdir "$temporary/source"
    tar -xzf "$temporary/source.tar.gz" --strip-components=1 -C "$temporary/source"
    SOURCE=$temporary/source
fi
SOURCE=$(cd "$SOURCE" && pwd)
for file in pyproject.toml uv.lock .env.example deploy/iran-internet-monitor.service deploy/iran-monitor; do
    [[ -f $SOURCE/$file ]] || fail "Source checkout is missing $file"
done
release="$PREFIX/releases/$(date -u +%Y%m%dT%H%M%SZ)-$$"
mkdir "$release"
tar -C "$SOURCE" --exclude='__pycache__' -cf - iran_monitor pyproject.toml uv.lock .env.example deploy README.md install.sh |
    tar -C "$release" -xf -
printf '%s\n' "$REF" >"$release/SOURCE_REF"
echo 'Installing isolated Python and locked binary dependencies (no C/C++ compilation)...'
UV_PYTHON_INSTALL_DIR="$PREFIX/python" UV_CACHE_DIR="$temporary/uv-cache" \
    UV_CONCURRENT_DOWNLOADS=2 UV_CONCURRENT_INSTALLS=1 UV_CONCURRENT_BUILDS=1 \
    nice -n 10 "$PREFIX/bin/uv" sync --project "$release" --python 3.12 --managed-python \
        --locked --no-dev --no-install-project --no-build --link-mode copy --no-progress
(cd "$release"; "$release/.venv/bin/python" -c 'import iran_monitor.app')
if ! getent passwd iran-monitor >/dev/null; then
    useradd --system --user-group --home-dir /var/lib/iran-internet-monitor --shell /usr/sbin/nologin iran-monitor
else
    [[ $(getent passwd iran-monitor | cut -d: -f6) == /var/lib/iran-internet-monitor ]] || fail 'Existing iran-monitor account belongs to another application'
fi
install -d -m 0750 -o root -g iran-monitor /etc/iran-internet-monitor
install -d -m 0700 -o iran-monitor -g iran-monitor /var/lib/iran-internet-monitor /var/cache/iran-internet-monitor
if [[ ! -f $CONFIG ]]; then
    install -m 0640 -o root -g iran-monitor "$release/.env.example" "$CONFIG"
fi
if ! "$NO_START"; then
    if ! (cd "$release"; "$release/.venv/bin/python" -c 'import sys; from pathlib import Path; from iran_monitor.config import Config, load_env; Config.from_values(load_env(Path(sys.argv[1])))' "$CONFIG") 2>/dev/null; then
        [[ -r /dev/tty ]] || fail 'A terminal is required for credentials; use --no-start for unattended installation'
        (cd "$release"; "$release/.venv/bin/python" -m iran_monitor --env "$CONFIG" configure </dev/tty)
        chown root:iran-monitor "$CONFIG"
        chmod 0640 "$CONFIG"
    fi
    (cd "$release"; "$release/.venv/bin/python" -m iran_monitor --env "$CONFIG" check)
fi
old_release=$(readlink -f "$PREFIX/current" 2>/dev/null || true)
was_active=false
if systemctl is-active --quiet "$UNIT"; then was_active=true; fi
install -m 0644 "$release/deploy/$UNIT" "/etc/systemd/system/$UNIT"
install -m 0755 "$release/deploy/iran-monitor" /usr/local/bin/iran-monitor
ln -s "$release" "$PREFIX/.current-new"
mv -Tf "$PREFIX/.current-new" "$PREFIX/current"
activated=true
systemctl daemon-reload
if ! "$NO_START"; then
    systemctl enable "$UNIT"
    if ! systemctl restart "$UNIT"; then
        if [[ -n $old_release && -d $old_release ]]; then
            ln -s "$old_release" "$PREFIX/.current-rollback"
            mv -Tf "$PREFIX/.current-rollback" "$PREFIX/current"
            install -m 0644 "$old_release/deploy/$UNIT" "/etc/systemd/system/$UNIT"
            install -m 0755 "$old_release/deploy/iran-monitor" /usr/local/bin/iran-monitor
            systemctl daemon-reload
            if "$was_active"; then systemctl restart "$UNIT" || true; fi
        fi
        fail 'Service could not start; previous code was restored where available'
    fi
fi
# Keep only the active release and its predecessor. Never remove config or state.
for candidate in "$PREFIX"/releases/*; do
    if [[ -d $candidate && $candidate != "$release" && $candidate != "$old_release" ]]; then
        rm -rf "$candidate"
    fi
done
echo 'Installation complete. Config and state survive updates.'
if "$NO_START"; then
    echo 'Service was not started. Next: sudo iran-monitor configure'
else
    echo 'Service started. Use: sudo iran-monitor status'
fi
echo 'Logs: sudo iran-monitor logs | Resource use: sudo iran-monitor resources'
