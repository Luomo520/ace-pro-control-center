#!/usr/bin/env bash
set -Eeuo pipefail

PROGRAM=${0##*/}
SCRIPT_DIR=$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd -P)
REPO_DIR=$(cd -- "$SCRIPT_DIR/.." && pwd -P)
ACTION=install
ROOT=/
INSTALL_HOME=${HOME:-/home/pi}
KLIPPER_HOME=
MOONRAKER_HOME=
PRINTER_DATA=
CONFIG_DIR_INPUT=
FLUIDD_HOME=
FLUIDD_SOURCE=
FLUIDD_MODE=auto
FLUIDD_OVERLAY_ENABLED=0
NON_INTERACTIVE=0
DRY_RUN=0
DEVICE_COUNT=
declare -a DEVICE_SPECS=()
declare -a SNAPSHOT_TARGETS=()
declare -ar KLIPPER_WRAPPERS=(ace_hardware ace_device ace_machine ace_encoder)
TXN_DIR=
TXN_LOG=
TXN_ACTIVE=0
SNAPSHOT_DIR=
PYTHON_BIN=${PYTHON_BIN:-}
KLIPPER_PYTHON=
SKIP_KLIPPER_RUNTIME_CHECK=0
GENERATED_CFG=
PREVIEW_CFG=
PRODUCT_NAME='Ace Pro Control Center'
PRODUCT_VERSION='V2.5ahpha'

usage() {
    cat <<'EOF'
Ace Pro Control Center V2.5ahpha installer

Usage:
  installer/install.sh [options]
  installer/install.sh --uninstall [path options]

Install options:
  --device-count N            Configure 1-4 devices
  --device SPEC               Repeat in ace0.. order. Format:
                              MODEL|SERIAL[|BUS_ID|UID]
  --non-interactive           Never prompt; all device data is required
  --dry-run                   Validate and print operations without writing
  --check-compatibility       Probe Klipper/Fluidd and exit without installing

Path options:
  --root DIR                  Prefix default Linux paths (test/staging root)
  --home PATH                 Virtual install home (default: current $HOME)
  --klipper-home PATH         Klipper checkout
  --moonraker-home PATH       Moonraker checkout
  --printer-data PATH         Klipper printer_data directory
  --config-dir PATH           Config directory for legacy/custom layouts
  --klipper-python PATH       Python executable used by the Klipper service
  --fluidd-home PATH          Built Fluidd static directory
  --fluidd-source PATH        Optional Fluidd source checkout for source overlay
  --fluidd-mode MODE          auto, source, or standalone (default: auto)
  --repo PATH                 Ace Pro Control Center checkout

Other:
  --uninstall                 Remove only managed links and config blocks
  -h, --help                  Show this help

Paths passed explicitly are virtual absolute paths when --root is used.
The installer never restarts services or sends G-code.
Fluidd auto mode uses a compatible source overlay when possible and otherwise
keeps the version-independent /ace-v3/ standalone page.
EOF
}

die() { printf 'ERROR: %s\n' "$*" >&2; exit 1; }
info() { printf '%s %s: %s\n' "$PRODUCT_NAME" "$PRODUCT_VERSION" "$*"; }

need_arg() {
    [ "$#" -ge 2 ] || die "$1 requires a value"
}

while [ "$#" -gt 0 ]; do
    case "$1" in
        --uninstall) ACTION=uninstall; shift ;;
        --check-compatibility) ACTION=check; shift ;;
        --non-interactive) NON_INTERACTIVE=1; shift ;;
        --dry-run) DRY_RUN=1; shift ;;
        --device-count) need_arg "$@"; DEVICE_COUNT=$2; shift 2 ;;
        --device) need_arg "$@"; DEVICE_SPECS+=("$2"); shift 2 ;;
        --root) need_arg "$@"; ROOT=$2; shift 2 ;;
        --home) need_arg "$@"; INSTALL_HOME=$2; shift 2 ;;
        --klipper-home) need_arg "$@"; KLIPPER_HOME=$2; shift 2 ;;
        --moonraker-home) need_arg "$@"; MOONRAKER_HOME=$2; shift 2 ;;
        --printer-data) need_arg "$@"; PRINTER_DATA=$2; shift 2 ;;
        --config-dir) need_arg "$@"; CONFIG_DIR_INPUT=$2; shift 2 ;;
        --klipper-python) need_arg "$@"; KLIPPER_PYTHON=$2; shift 2 ;;
        --fluidd-home) need_arg "$@"; FLUIDD_HOME=$2; shift 2 ;;
        --fluidd-source) need_arg "$@"; FLUIDD_SOURCE=$2; shift 2 ;;
        --fluidd-mode) need_arg "$@"; FLUIDD_MODE=$2; shift 2 ;;
        --repo) need_arg "$@"; REPO_DIR=$2; shift 2 ;;
        -h|--help) usage; exit 0 ;;
        *) die "unknown option: $1" ;;
    esac
done

[ "${ROOT#/}" != "$ROOT" ] || die "--root must be absolute"
[ "${INSTALL_HOME#/}" != "$INSTALL_HOME" ] || die "--home must be absolute"
ROOT=${ROOT%/}
[ -n "$ROOT" ] || ROOT=/
case "$FLUIDD_MODE" in
    auto|source|standalone) ;;
    *) die "--fluidd-mode must be auto, source, or standalone" ;;
esac

root_path() {
    local path=$1
    [ "${path#/}" != "$path" ] || die "target path must be absolute: $path"
    if [ "$ROOT" = / ]; then
        printf '%s\n' "$path"
    else
        printf '%s%s\n' "$ROOT" "$path"
    fi
}

discover_virtual_dir() {
    local candidate resolved
    for candidate in "$@"; do
        resolved=$(root_path "$candidate")
        if [ -d "$resolved" ]; then
            printf '%s\n' "$candidate"
            return 0
        fi
    done
    return 1
}

discover_virtual_config() {
    local candidate resolved
    for candidate in "$@"; do
        resolved=$(root_path "$candidate")
        if [ -f "$resolved/printer.cfg" ]; then
            printf '%s\n' "$candidate"
            return 0
        fi
    done
    return 1
}

if [ -z "$KLIPPER_HOME" ]; then
    KLIPPER_HOME=$(discover_virtual_dir \
        "$INSTALL_HOME/klipper" "$INSTALL_HOME/klipper-master" \
        /opt/klipper /usr/share/klipper || printf '%s\n' "$INSTALL_HOME/klipper")
fi
if [ -z "$MOONRAKER_HOME" ]; then
    MOONRAKER_HOME=$(discover_virtual_dir \
        "$INSTALL_HOME/moonraker" "$INSTALL_HOME/moonraker-master" \
        /opt/moonraker /usr/share/moonraker || printf '%s\n' "$INSTALL_HOME/moonraker")
fi
if [ -z "$CONFIG_DIR_INPUT" ]; then
    if [ -n "$PRINTER_DATA" ]; then
        CONFIG_DIR_INPUT=$PRINTER_DATA/config
    else
        CONFIG_DIR_INPUT=$(discover_virtual_config \
            "$INSTALL_HOME/printer_data/config" \
            "$INSTALL_HOME/klipper_config" \
            "$INSTALL_HOME" || printf '%s\n' "$INSTALL_HOME/printer_data/config")
    fi
fi
if [ -z "$PRINTER_DATA" ]; then
    if [ "${CONFIG_DIR_INPUT%/config}" != "$CONFIG_DIR_INPUT" ]; then
        PRINTER_DATA=${CONFIG_DIR_INPUT%/config}
    else
        PRINTER_DATA=$(dirname -- "$CONFIG_DIR_INPUT")
    fi
fi
if [ -z "$FLUIDD_HOME" ]; then
    FLUIDD_HOME=$(discover_virtual_dir \
        "$INSTALL_HOME/fluidd" /usr/share/fluidd /var/www/fluidd \
        || printf '%s\n' "$INSTALL_HOME/fluidd")
fi
if [ "$ACTION" = install ] && [ "$NON_INTERACTIVE" -eq 0 ] \
    && [ "$FLUIDD_MODE" != standalone ] && [ -z "$FLUIDD_SOURCE" ]; then
    read -r -p 'Fluidd source checkout for card overlay (blank to skip): ' FLUIDD_SOURCE
fi

KLIPPER_HOME=$(root_path "$KLIPPER_HOME")
MOONRAKER_HOME=$(root_path "$MOONRAKER_HOME")
PRINTER_DATA=$(root_path "$PRINTER_DATA")
CONFIG_DIR=$(root_path "$CONFIG_DIR_INPUT")
FLUIDD_HOME=$(root_path "$FLUIDD_HOME")
if [ -n "$FLUIDD_SOURCE" ]; then
    FLUIDD_SOURCE=$(root_path "$FLUIDD_SOURCE")
fi
if [ -n "$KLIPPER_PYTHON" ]; then
    KLIPPER_PYTHON=$(root_path "$KLIPPER_PYTHON")
fi
REPO_DIR=$(cd -- "$REPO_DIR" 2>/dev/null && pwd -P) || die "repository not found: $REPO_DIR"

STATE_DIR=$CONFIG_DIR/.ace-driver-v3
SNAPSHOT_BASE=$PRINTER_DATA/ace-driver-v3-snapshots
MANIFEST=$STATE_DIR/links.manifest
FLUIDD_PATCH_STATE=$STATE_DIR/fluidd-source.path
LEGACY_DIR=$STATE_DIR/legacy
LEGACY_HARDWARE_ARCHIVE=$LEGACY_DIR/ace_hardware.cfg
PACKAGE_SOURCE=$REPO_DIR/ace_driver
PACKAGE_TARGET=$KLIPPER_HOME/klippy/extras/ace
WRAPPER_SOURCE=$REPO_DIR/klipper_extras
MOON_SOURCE=$REPO_DIR/moonraker/ace_status.py
MOON_TARGET=$MOONRAKER_HOME/moonraker/components/ace_status.py
DASHBOARD_SOURCE=$REPO_DIR/frontend/dashboard
SHARED_FRONTEND_SOURCE=$REPO_DIR/frontend/shared
OVERLAY_SOURCE=$REPO_DIR/frontend/fluidd-overlay
PRINTER_CFG=$CONFIG_DIR/printer.cfg
MOONRAKER_CFG=$CONFIG_DIR/moonraker.conf
SHARED_CFG=$CONFIG_DIR/ace.cfg
LEGACY_HARDWARE_CFG=$CONFIG_DIR/ace_hardware.cfg
MACHINE_CFG=$CONFIG_DIR/ace_machine.cfg

path_exists() { [ -e "$1" ] || [ -L "$1" ]; }

manifest_has_link() {
    local target=$1
    [ -f "$MANIFEST" ] &&
        awk -F '|' -v path="$target" '$1 == path { found=1 } END { exit !found }' "$MANIFEST"
}

select_installer_python() {
    if [ -z "$PYTHON_BIN" ]; then
        PYTHON_BIN=$(command -v python3 || command -v python || true)
    fi
    [ -n "$PYTHON_BIN" ] && "$PYTHON_BIN" -c \
        'import sys; raise SystemExit(0 if sys.version_info >= (3, 8) else 1)' \
        >/dev/null 2>&1 ||
        die "Python 3.8 or newer is required (or set PYTHON_BIN)"
}

select_klipper_python() {
    local candidate
    if [ -n "$KLIPPER_PYTHON" ]; then
        [ -x "$KLIPPER_PYTHON" ] || die "Klipper Python is not executable: $KLIPPER_PYTHON"
        return 0
    fi
    for candidate in \
        "$(root_path "$INSTALL_HOME/klippy-env/bin/python")" \
        "$(root_path "$INSTALL_HOME/klipper-env/bin/python")" \
        "$(dirname -- "$KLIPPER_HOME")/klippy-env/bin/python" \
        "$(dirname -- "$KLIPPER_HOME")/klipper-env/bin/python" \
        "$(root_path /usr/bin/python3)"; do
        if [ -x "$candidate" ]; then
            KLIPPER_PYTHON=$candidate
            return 0
        fi
    done
    if [ "$ROOT" != / ]; then
        SKIP_KLIPPER_RUNTIME_CHECK=1
        info "staging root has no executable Klipper Python; runtime check will be reported as skipped"
        return 0
    fi
    KLIPPER_PYTHON=$PYTHON_BIN
    info "Klipper virtualenv was not detected; probing fallback Python: $KLIPPER_PYTHON"
}

check_klipper_compatibility() {
    local args=(check --repo "$REPO_DIR" --klipper-home "$KLIPPER_HOME")
    local report status summary
    if [ "$SKIP_KLIPPER_RUNTIME_CHECK" -eq 1 ]; then
        args+=(--skip-runtime-check)
    else
        args+=(--python "$KLIPPER_PYTHON")
    fi
    if report=$("$PYTHON_BIN" "$REPO_DIR/scripts/klipper_compat.py" "${args[@]}"); then
        status=0
    else
        status=$?
    fi
    summary=$(printf '%s' "$report" | "$PYTHON_BIN" -c '
import json, sys
data = json.load(sys.stdin)
runtime = data.get("runtime", {})
if data.get("compatible"):
    if runtime.get("skipped"):
        runtime_text = "runtime probe skipped"
    else:
        runtime_text = "Python %s, pyserial %s" % (
            runtime.get("python", {}).get("version", "unknown"),
            runtime.get("pyserial", {}).get("version", "unknown"),
        )
    print("capabilities passed (%s)" % runtime_text)
else:
    print("; ".join(data.get("errors", [])) or "unknown compatibility error")
' 2>/dev/null) || summary="compatibility probe returned an unreadable report"
    if [ "$status" -eq 0 ]; then
        info "Klipper compatibility: $summary"
    else
        printf 'Klipper compatibility failed: %s\n' "$summary" >&2
        return "$status"
    fi
}

prepare_fluidd_compatibility() {
    local report summary guide has_build
    FLUIDD_OVERLAY_ENABLED=0
    if [ "$FLUIDD_MODE" = standalone ]; then
        info "Fluidd standalone mode selected; native source overlay will not be modified"
        return 0
    fi
    if [ -z "$FLUIDD_SOURCE" ]; then
        [ "$FLUIDD_MODE" != source ] ||
            die "--fluidd-mode source requires --fluidd-source"
        info "no Fluidd source was supplied; using the version-independent /ace-v3/ page"
        return 0
    fi
    if report=$("$PYTHON_BIN" "$REPO_DIR/scripts/fluidd_overlay.py" inspect "$FLUIDD_SOURCE" 2>&1); then
        summary=$(printf '%s' "$report" | "$PYTHON_BIN" -c '
import json, sys
data = json.load(sys.stdin)
print("%s (%s)" % (data["fluidd"]["version"], data["profile"]))
' 2>/dev/null) || summary="compatible source tree"
        guide=$("$PYTHON_BIN" "$REPO_DIR/scripts/fluidd_overlay.py" \
            build-guide "$FLUIDD_SOURCE" 2>&1) ||
            die "Fluidd build toolchain cannot be determined: $guide"
        has_build=$(printf '%s' "$guide" | "$PYTHON_BIN" -c '
import json, sys
print("yes" if json.load(sys.stdin).get("build_script_present") else "no")
' 2>/dev/null) || has_build=no
        if [ "$has_build" = yes ]; then
            FLUIDD_OVERLAY_ENABLED=1
            info "Fluidd source compatibility: $summary"
            return 0
        fi
        summary="$summary; package.json has no build script"
        if [ "$FLUIDD_MODE" = source ]; then
            die "Fluidd source cannot produce a deployable dist: $summary"
        fi
        info "Fluidd source overlay is incompatible and was skipped: $summary"
        info "the /ace-v3/ standalone page remains available"
        return 0
    fi
    summary=$(printf '%s' "$report" | "$PYTHON_BIN" -c '
import json, sys
data = json.load(sys.stdin)
print("; ".join(data.get("reasons", [])) or "unknown compatibility error")
' 2>/dev/null) || summary=$report
    if [ "$FLUIDD_MODE" = source ]; then
        printf '%s\n' "$summary" >&2
        die "Fluidd source is not compatible with the native ACE overlay"
    fi
    info "Fluidd source overlay is incompatible and was skipped: $summary"
    info "the /ace-v3/ standalone page remains available"
}

fluidd_patched_files() {
    "$PYTHON_BIN" "$REPO_DIR/scripts/fluidd_overlay.py" files
}

collect_snapshot_targets() {
    local source target relative name
    SNAPSHOT_TARGETS=(
        "$STATE_DIR"
        "$PACKAGE_TARGET"
        "$MOON_TARGET"
        "$SHARED_CFG"
        "$SHARED_CFG.new"
        "$LEGACY_HARDWARE_CFG"
        "$MACHINE_CFG"
        "$MACHINE_CFG.legacy"
        "$PRINTER_CFG"
        "$MOONRAKER_CFG"
    )
    for name in "${KLIPPER_WRAPPERS[@]}"; do
        SNAPSHOT_TARGETS+=("$KLIPPER_HOME/klippy/extras/$name.py")
    done
    while IFS= read -r -d '' source; do
        target=$FLUIDD_HOME/ace-v3/${source#"$DASHBOARD_SOURCE/"}
        SNAPSHOT_TARGETS+=("$target")
    done < <(find "$DASHBOARD_SOURCE" -type f -print0 | sort -z)
    while IFS= read -r -d '' source; do
        target=$FLUIDD_HOME/shared/${source#"$SHARED_FRONTEND_SOURCE/"}
        SNAPSHOT_TARGETS+=("$target")
    done < <(find "$SHARED_FRONTEND_SOURCE" -type f -print0 | sort -z)
    if [ "$FLUIDD_OVERLAY_ENABLED" -eq 1 ]; then
        while IFS= read -r -d '' source; do
            target=$FLUIDD_SOURCE/${source#"$OVERLAY_SOURCE/"}
            SNAPSHOT_TARGETS+=("$target")
        done < <(find "$OVERLAY_SOURCE/src" -type f ! -name ace-core.js -print0 | sort -z)
        SNAPSHOT_TARGETS+=(
            "$FLUIDD_SOURCE/src/components/widgets/ace-v3/ace-core.js"
        )
        while IFS= read -r relative; do
            [ -n "$relative" ] || continue
            SNAPSHOT_TARGETS+=("$FLUIDD_SOURCE/$relative")
        done < <(fluidd_patched_files)
    fi
}

create_install_snapshot() {
    local stamp suffix=0 candidate target
    [ "$DRY_RUN" -eq 0 ] || return 0
    collect_snapshot_targets
    stamp=$(date +%Y%m%d_%H%M%S)
    candidate=$SNAPSHOT_BASE/$stamp-before-install
    while path_exists "$candidate"; do
        suffix=$((suffix + 1))
        candidate=$SNAPSHOT_BASE/$stamp-before-install-$suffix
    done
    local args=(create --output "$candidate")
    for target in "${SNAPSHOT_TARGETS[@]}"; do
        args+=(--target "$target")
    done
    SNAPSHOT_DIR=$("$PYTHON_BIN" "$REPO_DIR/scripts/install_snapshot.py" \
        "${args[@]}") || die "persistent pre-install snapshot failed"
    info "persistent pre-install snapshot: $SNAPSHOT_DIR"
}

show_snapshot_recovery() {
    local command
    [ -n "$SNAPSHOT_DIR" ] || return 0
    printf -v command '%q ' "$PYTHON_BIN" "$SNAPSHOT_DIR/restore.py" \
        restore "$SNAPSHOT_DIR" --apply
    info "snapshot retained: $SNAPSHOT_DIR"
    info "restore command (stop Klipper and Moonraker first): ${command% }"
}

show_fluidd_build_guidance() {
    local report line
    report=$("$PYTHON_BIN" "$REPO_DIR/scripts/fluidd_overlay.py" \
        build-guide "$FLUIDD_SOURCE") || {
        info "Fluidd source was patched, but build guidance could not be generated"
        return 0
    }
    while IFS= read -r line; do
        info "$line"
    done < <(printf '%s' "$report" | "$PYTHON_BIN" -c '
import json, shlex, sys
data = json.load(sys.stdin)
live = sys.argv[1]
print("REQUIRED: the Fluidd source patch is not live until dist is built and deployed")
print("Fluidd toolchain: %s (%s)" % (data["toolchain"], data["toolchain_source"]))
for index, command in enumerate(data["shell_steps"], 1):
    print("Fluidd build step %d: %s" % (index, command))
print("Fluidd deploy step: verify %s/index.html, then atomically deploy only the contents of dist to %s" % (
    shlex.quote(data["dist"]), shlex.quote(live)))
print("Example deploy command: rsync -a --delete -- %s/ %s/" % (
    shlex.quote(data["dist"]), shlex.quote(live)))
' "$FLUIDD_HOME")
}

is_v3_shared_config() {
    local path=$1
    [ -f "$path" ] \
        && grep -Eiq '^[[:space:]]*\[ace\][[:space:]]*$' "$path" \
        && grep -Eiq '^[[:space:]]*driver_version[[:space:]]*:[[:space:]]*3([[:space:]]+[#;].*)?$' "$path"
}

begin_transaction() {
    [ "$DRY_RUN" -eq 0 ] || return 0
    TXN_DIR=$(mktemp -d "${TMPDIR:-/tmp}/ace-v3-install.XXXXXX")
    TXN_LOG=$TXN_DIR/changes
    : > "$TXN_LOG"
    TXN_ACTIVE=1
}

prepare_target() {
    local target=$1 record backup
    [ "$DRY_RUN" -eq 0 ] || return 0
    if awk -F '|' -v path="$target" '$2 == path { found=1 } END { exit !found }' "$TXN_LOG"; then
        return 0
    fi
    if path_exists "$target"; then
        backup=$TXN_DIR/backup-$(wc -l < "$TXN_LOG" | tr -d ' ')
        cp -a --no-dereference -- "$target" "$backup"
        record="existing|$target|$backup"
    else
        record="missing|$target|-"
    fi
    printf '%s\n' "$record" >> "$TXN_LOG"
}

rollback() {
    local status target backup
    [ "$TXN_ACTIVE" -eq 1 ] || return 0
    info "rolling back incomplete transaction"
    while IFS='|' read -r status target backup; do
        path_exists "$target" && rm -rf -- "$target"
        if [ "$status" = existing ]; then
            mkdir -p -- "$(dirname -- "$target")"
            cp -a --no-dereference -- "$backup" "$target"
        fi
    done < <(tac "$TXN_LOG")
    rm -rf -- "$TXN_DIR"
    TXN_ACTIVE=0
}

commit_transaction() {
    [ "$TXN_ACTIVE" -eq 1 ] || return 0
    rm -rf -- "$TXN_DIR"
    TXN_ACTIVE=0
}

on_exit() {
    local status=$?
    [ -z "$GENERATED_CFG" ] || rm -f -- "$GENERATED_CFG"
    [ -z "$PREVIEW_CFG" ] || rm -f -- "$PREVIEW_CFG"
    if [ "$status" -ne 0 ]; then
        rollback
        show_snapshot_recovery
    fi
    exit "$status"
}
trap on_exit EXIT

run_or_plan() {
    if [ "$DRY_RUN" -eq 1 ]; then
        printf 'DRY-RUN:'
        printf ' %q' "$@"
        printf '\n'
    else
        "$@"
    fi
}

record_link() {
    local target=$1 source=$2 backup=${3:--}
    [ "$DRY_RUN" -eq 0 ] || return 0
    prepare_target "$STATE_DIR"
    mkdir -p -- "$STATE_DIR"
    if [ ! -f "$MANIFEST" ] || ! awk -F '|' -v path="$target" '$1 == path { found=1 } END { exit !found }' "$MANIFEST"; then
        printf '%s|%s|%s\n' "$target" "$source" "$backup" >> "$MANIFEST"
    fi
}

install_link() {
    local source=$1 target=$2 replace=${3:-0} backup=- backup_name
    [ -e "$source" ] || die "installation source missing: $source"
    if [ -L "$target" ] && [ "$(readlink -- "$target")" = "$source" ]; then
        info "link already installed: $target"
        return 0
    fi
    if path_exists "$target"; then
        [ "$replace" -eq 1 ] || die "refusing to replace unmanaged path: $target"
        backup_name=$(printf '%s' "$target" | sha256sum | cut -c1-24)
        backup=$STATE_DIR/backups/$backup_name
        if [ "$DRY_RUN" -eq 0 ]; then
            prepare_target "$STATE_DIR"
            mkdir -p -- "$(dirname -- "$backup")"
            [ -e "$backup" ] || cp -a --no-dereference -- "$target" "$backup"
        fi
    fi
    info "link $target -> $source"
    if [ "$DRY_RUN" -eq 0 ]; then
        prepare_target "$target"
        mkdir -p -- "$(dirname -- "$target")"
        rm -rf -- "$target"
        ln -s -- "$source" "$target"
    fi
    record_link "$target" "$source" "$backup"
}

ensure_block() {
    local kind=$1 path=$2
    if [ "$kind" = moonraker ] && [ -f "$path" ] \
        && grep -Eiq '^[[:space:]]*\[ace_status\][[:space:]]*$' "$path" \
        && ! grep -Fq '# >>> ACE Driver V3 managed component >>>' "$path"; then
        die "unmanaged [ace_status] section detected; remove the V2 section before installing Ace Pro Control Center"
    fi
    info "ensure managed $kind block in $path"
    if [ "$DRY_RUN" -eq 1 ]; then
        "$PYTHON_BIN" "$REPO_DIR/scripts/managed_block.py" validate "$kind" "$path"
    else
        prepare_target "$path"
        mkdir -p -- "$(dirname -- "$path")"
        "$PYTHON_BIN" "$REPO_DIR/scripts/managed_block.py" ensure "$kind" "$path"
    fi
}

upgrade_config_contract() {
    local kind=$1 template=$2 target=$3 legacy=${4:-}
    [ -f "$target" ] || return 0
    info "upgrade $kind configuration contract while preserving user calibration: $target"
    if [ "$DRY_RUN" -eq 1 ]; then
        local args=("$kind" "$template" "$target" --check)
        [ "$kind" = merged ] && args+=(--legacy-machine "$legacy")
        "$PYTHON_BIN" "$REPO_DIR/scripts/config_upgrade.py" "${args[@]}"
    else
        prepare_target "$target"
        local args=("$kind" "$template" "$target")
        [ "$kind" = merged ] && args+=(--legacy-machine "$legacy")
        "$PYTHON_BIN" "$REPO_DIR/scripts/config_upgrade.py" "${args[@]}"
    fi
}

archive_legacy_machine_config() {
    local legacy_target=$MACHINE_CFG.legacy
    [ -e "$MACHINE_CFG" ] || [ -L "$MACHINE_CFG" ] || return 0
    [ ! -e "$legacy_target" ] && [ ! -L "$legacy_target" ] ||
        die "legacy machine config archive already exists: $legacy_target"
    info "archive retired machine macro configuration: $legacy_target"
    [ "$DRY_RUN" -eq 0 ] || return 0
    prepare_target "$MACHINE_CFG"
    prepare_target "$legacy_target"
    mv -- "$MACHINE_CFG" "$legacy_target"
}

archive_legacy_hardware_config() {
    local archive=$LEGACY_HARDWARE_ARCHIVE stamp suffix=0
    path_exists "$LEGACY_HARDWARE_CFG" || return 0
    if path_exists "$archive"; then
        stamp=$(date +%Y%m%d_%H%M%S)
        archive=$LEGACY_DIR/ace_hardware.$stamp.cfg
        while path_exists "$archive"; do
            suffix=$((suffix + 1))
            archive=$LEGACY_DIR/ace_hardware.$stamp.$suffix.cfg
        done
    fi
    info "archive retired hardware configuration: $archive"
    [ "$DRY_RUN" -eq 0 ] || return 0
    prepare_target "$LEGACY_HARDWARE_CFG"
    prepare_target "$LEGACY_DIR"
    mkdir -p -- "$LEGACY_DIR"
    mv -- "$LEGACY_HARDWARE_CFG" "$archive"
}

collect_interactive_devices() {
    local index model serial bus uid
    if [ -z "$DEVICE_COUNT" ]; then
        read -r -p 'ACE device count [1-4]: ' DEVICE_COUNT
    fi
    [[ "$DEVICE_COUNT" =~ ^[1-4]$ ]] || die "device count must be 1-4"
    if [ "${#DEVICE_SPECS[@]}" -gt 0 ]; then return 0; fi
    for ((index=0; index<DEVICE_COUNT; index++)); do
        read -r -p "ace$index model [ace1/ace2/auto]: " model
        read -r -p "ace$index stable serial path: " serial
        case "$model" in
            ace2)
                read -r -p "ace$index ACE2 bus_id [ace2bus0]: " bus
                bus=${bus:-ace2bus0}
                read -r -p "ace$index ACE2 UID (required): " uid
                [ -n "$uid" ] || die "ace$index ACE2 requires an explicit UID"
                DEVICE_SPECS+=("$model|$serial|$bus|$uid")
                ;;
            ace1|auto) DEVICE_SPECS+=("$model|$serial") ;;
            *) die "unsupported model: $model" ;;
        esac
    done
}

collect_devices() {
    if [ "$NON_INTERACTIVE" -eq 0 ]; then
        collect_interactive_devices
    else
        [ -n "$DEVICE_COUNT" ] || DEVICE_COUNT=${#DEVICE_SPECS[@]}
    fi
    [[ "$DEVICE_COUNT" =~ ^[1-4]$ ]] || die "device count must be 1-4"
    [ "${#DEVICE_SPECS[@]}" -eq "$DEVICE_COUNT" ] ||
        die "--device-count must match the number of --device arguments"
}

generate_hardware() {
    local output=$1 spec preserve= embedded=0
    local args=(generate --output "$output")
    if [ -f "$SHARED_CFG" ] && {
        grep -Fq '# >>> ACE DRIVER V3 HARDWARE TOPOLOGY BEGIN >>>' "$SHARED_CFG" ||
            grep -Fq '# <<< ACE DRIVER V3 HARDWARE TOPOLOGY END <<<' "$SHARED_CFG"
    }; then
        "$PYTHON_BIN" "$REPO_DIR/scripts/hardware_config.py" \
            validate-embedded "$SHARED_CFG" >/dev/null ||
            die "existing ace.cfg has an invalid embedded hardware topology"
        embedded=1
    fi
    if [ -f "$LEGACY_HARDWARE_CFG" ] && [ "$embedded" -eq 1 ]; then
        die "both embedded hardware topology and ace_hardware.cfg are active; remove the stale source before reinstalling"
    fi
    if [ -f "$LEGACY_HARDWARE_CFG" ]; then
        preserve=$LEGACY_HARDWARE_CFG
    elif [ "$embedded" -eq 1 ]; then
        preserve=$SHARED_CFG
    fi
    [ -z "$preserve" ] || args+=(--preserve-from "$preserve")
    for spec in "${DEVICE_SPECS[@]}"; do args+=(--device "$spec"); done
    "$PYTHON_BIN" "$REPO_DIR/scripts/hardware_config.py" "${args[@]}"
    "$PYTHON_BIN" "$REPO_DIR/scripts/hardware_config.py" validate "$output"
}

merge_generated_hardware() {
    local target=$1 generated=$2 spec
    local args=(merge "$target" --preserve-from "$generated")
    for spec in "${DEVICE_SPECS[@]}"; do args+=(--device "$spec"); done
    "$PYTHON_BIN" "$REPO_DIR/scripts/hardware_config.py" "${args[@]}"
    "$PYTHON_BIN" "$REPO_DIR/scripts/hardware_config.py" \
        validate-embedded "$target"
}

validate_targets() {
    [ -d "$KLIPPER_HOME/klippy/extras" ] || die "Klipper extras directory missing: $KLIPPER_HOME/klippy/extras"
    [ ! -e "$KLIPPER_HOME/klippy/extras/ace.py" ] ||
        die "legacy ACE ace.py detected; back up and uninstall V2 before installing Ace Pro Control Center"
    [ -d "$MOONRAKER_HOME/moonraker/components" ] || die "Moonraker components directory missing: $MOONRAKER_HOME/moonraker/components"
    [ -d "$CONFIG_DIR" ] || die "printer config directory missing: $CONFIG_DIR"
    [ -d "$FLUIDD_HOME" ] || die "Fluidd static directory missing: $FLUIDD_HOME"
    if [ -L "$PACKAGE_TARGET" ] && [ "$(readlink -- "$PACKAGE_TARGET")" = "$PACKAGE_SOURCE" ] \
        && ! manifest_has_link "$PACKAGE_TARGET"; then
        die "Klipper checkout is already linked to Ace Pro Control Center but is owned by another or unknown config directory; pass the original --config-dir or remove the unmanaged link"
    fi
    if path_exists "$MOON_TARGET" && ! { [ -L "$MOON_TARGET" ] && [ "$(readlink -- "$MOON_TARGET")" = "$MOON_SOURCE" ]; }; then
        die "existing Moonraker ace_status.py is not managed by Ace Pro Control Center; back up and uninstall V2 first"
    fi
    if [ -e "$SHARED_CFG" ] && ! is_v3_shared_config "$SHARED_CFG"; then
        die "existing ace.cfg is not an Ace Pro Control Center shared config; back up and uninstall V2 first"
    fi
    if [ "$FLUIDD_OVERLAY_ENABLED" -eq 1 ]; then
        [ -d "$FLUIDD_SOURCE/src" ] || die "Fluidd source directory missing src/: $FLUIDD_SOURCE"
    fi
}

install_dashboard() {
    local source target
    while IFS= read -r -d '' source; do
        target=$FLUIDD_HOME/ace-v3/${source#"$DASHBOARD_SOURCE/"}
        install_link "$source" "$target" 0
    done < <(find "$DASHBOARD_SOURCE" -type f -print0 | sort -z)
    while IFS= read -r -d '' source; do
        target=$FLUIDD_HOME/shared/${source#"$SHARED_FRONTEND_SOURCE/"}
        install_link "$source" "$target" 0
    done < <(find "$SHARED_FRONTEND_SOURCE" -type f -print0 | sort -z)
}

install_klipper_entries() {
    local name
    install_link "$PACKAGE_SOURCE" "$PACKAGE_TARGET" 0
    for name in "${KLIPPER_WRAPPERS[@]}"; do
        install_link "$WRAPPER_SOURCE/$name.py" \
            "$KLIPPER_HOME/klippy/extras/$name.py" 0
    done
}

install_overlay() {
    local source target relative
    [ "$FLUIDD_OVERLAY_ENABLED" -eq 1 ] || {
        info "Fluidd source overlay skipped; standalone page installed"
        return 0
    }
    "$PYTHON_BIN" "$REPO_DIR/scripts/fluidd_overlay.py" check "$FLUIDD_SOURCE"
    while IFS= read -r -d '' source; do
        target=$FLUIDD_SOURCE/${source#"$OVERLAY_SOURCE/"}
        install_link "$source" "$target" 1
    done < <(find "$OVERLAY_SOURCE/src" -type f ! -name ace-core.js -print0 | sort -z)
    install_link "$SHARED_FRONTEND_SOURCE/ace-core.js" \
        "$FLUIDD_SOURCE/src/components/widgets/ace-v3/ace-core.js" 1
    info "register card, page, route, and navigation in Fluidd source"
    if [ "$DRY_RUN" -eq 0 ]; then
        while IFS= read -r relative; do
            [ -n "$relative" ] || continue
            prepare_target "$FLUIDD_SOURCE/$relative"
        done < <(fluidd_patched_files)
        "$PYTHON_BIN" "$REPO_DIR/scripts/fluidd_overlay.py" apply "$FLUIDD_SOURCE"
        prepare_target "$FLUIDD_PATCH_STATE"
        printf '%s\n' "$FLUIDD_SOURCE" > "$FLUIDD_PATCH_STATE"
    fi
}

do_install() {
    local generated
    select_installer_python
    select_klipper_python
    command -v sha256sum >/dev/null || die "sha256sum is required"
    check_klipper_compatibility
    prepare_fluidd_compatibility
    collect_devices
    "$PYTHON_BIN" "$REPO_DIR/scripts/validate_release.py" --repo "$REPO_DIR" --require-frontend
    validate_targets
    "$PYTHON_BIN" "$REPO_DIR/scripts/config_preflight.py" \
        "$PRINTER_CFG" --device-count "$DEVICE_COUNT" \
        --allow-legacy-hardware-migration

    generated=$(mktemp "${TMPDIR:-/tmp}/ace-hardware.XXXXXX.cfg")
    GENERATED_CFG=$generated
    generate_hardware "$generated"
    create_install_snapshot
    begin_transaction

    install_klipper_entries
    install_link "$MOON_SOURCE" "$MOON_TARGET" 0
    install_dashboard
    install_overlay

    if [ ! -e "$SHARED_CFG" ]; then
        info "install shared configuration: $SHARED_CFG"
        if [ "$DRY_RUN" -eq 0 ]; then
            prepare_target "$SHARED_CFG"
            prepare_target "$SHARED_CFG.new"
            cp -- "$REPO_DIR/config/ace.cfg" "$SHARED_CFG.new"
            mv -- "$SHARED_CFG.new" "$SHARED_CFG"
        fi
    else
        is_v3_shared_config "$SHARED_CFG" ||
            die "existing ace.cfg is not an Ace Pro Control Center shared config; move the V2 file before installing"
        info "preserve existing shared configuration: $SHARED_CFG"
    fi

    upgrade_config_contract merged "$REPO_DIR/config/ace.cfg" "$SHARED_CFG" "$MACHINE_CFG"
    archive_legacy_machine_config

    info "merge generated hardware topology into: $SHARED_CFG"
    if [ "$DRY_RUN" -eq 1 ]; then
        PREVIEW_CFG=$(mktemp "${TMPDIR:-/tmp}/ace-shared-preview.XXXXXX.cfg")
        if [ -f "$SHARED_CFG" ]; then
            cp -- "$SHARED_CFG" "$PREVIEW_CFG"
            local preview_args=(
                merged "$REPO_DIR/config/ace.cfg" "$PREVIEW_CFG"
            )
            [ ! -f "$MACHINE_CFG" ] ||
                preview_args+=(--legacy-machine "$MACHINE_CFG")
            "$PYTHON_BIN" "$REPO_DIR/scripts/config_upgrade.py" \
                "${preview_args[@]}"
        else
            cp -- "$REPO_DIR/config/ace.cfg" "$PREVIEW_CFG"
        fi
        merge_generated_hardware "$PREVIEW_CFG" "$generated"
        rm -f -- "$PREVIEW_CFG"
        PREVIEW_CFG=
    else
        prepare_target "$SHARED_CFG"
        merge_generated_hardware "$SHARED_CFG" "$generated"
    fi
    archive_legacy_hardware_config
    rm -f -- "$generated"
    GENERATED_CFG=

    ensure_block printer "$PRINTER_CFG"
    ensure_block moonraker "$MOONRAKER_CFG"
    if [ "$DRY_RUN" -eq 0 ]; then
        info "run strict post-migration include preflight"
        "$PYTHON_BIN" "$REPO_DIR/scripts/config_preflight.py" \
            "$PRINTER_CFG" --device-count "$DEVICE_COUNT"
    fi
    commit_transaction
    if [ "$DRY_RUN" -eq 1 ]; then
        info "dry-run complete; no target files were changed"
    else
        info "installation complete; services were not restarted"
        show_snapshot_recovery
        info "review $SHARED_CFG before restarting Klipper"
        if [ "$FLUIDD_OVERLAY_ENABLED" -eq 1 ]; then
            show_fluidd_build_guidance
        else
            info "Fluidd native card was not patched; use $FLUIDD_HOME/ace-v3/ through the Fluidd web root"
        fi
    fi
}

do_compatibility_check() {
    select_installer_python
    select_klipper_python
    [ -d "$KLIPPER_HOME/klippy/extras" ] ||
        die "Klipper extras directory missing: $KLIPPER_HOME/klippy/extras"
    [ -d "$MOONRAKER_HOME/moonraker/components" ] ||
        die "Moonraker components directory missing: $MOONRAKER_HOME/moonraker/components"
    [ -d "$FLUIDD_HOME" ] || die "Fluidd static directory missing: $FLUIDD_HOME"
    check_klipper_compatibility
    prepare_fluidd_compatibility
    info "compatibility check complete; no target files were changed"
}

remove_managed_block() {
    local kind=$1 path=$2
    [ -e "$path" ] || return 0
    info "remove managed $kind block from $path"
    if [ "$DRY_RUN" -eq 0 ]; then
        prepare_target "$path"
        "$PYTHON_BIN" "$REPO_DIR/scripts/managed_block.py" remove "$kind" "$path"
    fi
}

remove_overlay_patch() {
    local source_root=$FLUIDD_SOURCE relative path
    if [ -z "$source_root" ] && [ -f "$FLUIDD_PATCH_STATE" ]; then
        source_root=$(head -n 1 "$FLUIDD_PATCH_STATE")
    fi
    [ -n "$source_root" ] || return 0
    if [ ! -d "$source_root" ]; then
        info "Fluidd source directory no longer exists; skip source marker cleanup: $source_root"
        return 0
    fi
    info "remove dashboard, route, and navigation registration from Fluidd source"
    if [ "$DRY_RUN" -eq 0 ]; then
        while IFS= read -r relative; do
            [ -n "$relative" ] || continue
            path=$source_root/$relative
            if [ -f "$path" ]; then
                prepare_target "$path"
            else
                info "Fluidd source file is absent after an upgrade; skip it: $path"
            fi
        done < <(fluidd_patched_files)
        "$PYTHON_BIN" "$REPO_DIR/scripts/fluidd_overlay.py" remove "$source_root"
    fi
}

cleanup_installer_state() {
    local target
    [ -d "$STATE_DIR" ] || return 0
    if [ -d "$LEGACY_DIR" ]; then
        info "preserve migrated legacy configuration archive: $LEGACY_DIR"
        for target in "$MANIFEST" "$FLUIDD_PATCH_STATE" "$STATE_DIR/backups"; do
            path_exists "$target" || continue
            prepare_target "$target"
            rm -rf -- "$target"
        done
        return 0
    fi
    prepare_target "$STATE_DIR"
    rm -rf -- "$STATE_DIR"
}

do_uninstall() {
    local target source backup
    select_installer_python
    begin_transaction
    remove_overlay_patch
    if [ -f "$MANIFEST" ]; then
        while IFS='|' read -r target source backup; do
            if [ -L "$target" ] && [ "$(readlink -- "$target")" = "$source" ]; then
                info "remove managed link: $target"
                if [ "$DRY_RUN" -eq 0 ]; then
                    prepare_target "$target"
                    rm -- "$target"
                    if [ "$backup" != - ] && [ -e "$backup" ]; then
                        cp -a --no-dereference -- "$backup" "$target"
                    fi
                fi
            elif path_exists "$target"; then
                info "preserve changed or unmanaged path: $target"
            fi
        done < <(tac "$MANIFEST")
    else
        info "no install manifest found; no links will be removed"
    fi
    remove_managed_block printer "$PRINTER_CFG"
    remove_managed_block moonraker "$MOONRAKER_CFG"
    if [ "$DRY_RUN" -eq 0 ]; then
        cleanup_installer_state
    elif [ -d "$LEGACY_DIR" ]; then
        info "preserve migrated legacy configuration archive: $LEGACY_DIR"
    fi
    commit_transaction
    info "uninstall complete; user configuration and services were left untouched"
}

case "$ACTION" in
    install) do_install ;;
    uninstall) do_uninstall ;;
    check) do_compatibility_check ;;
esac
trap - EXIT
