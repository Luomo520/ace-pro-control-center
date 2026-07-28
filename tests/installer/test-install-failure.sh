#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR=$(CDPATH= cd -- "$(dirname -- "$0")/../.." && pwd)
TEST_ROOT=$(mktemp -d "${TMPDIR:-/tmp}/ace-control-center-installer-failure.XXXXXX")
export HOME="$TEST_ROOT/home"
export FLUIDD_ROOT="$HOME/fluidd"
export KLIPPER_ROOT="$HOME/klipper"
export MOONRAKER_ROOT="$HOME/moonraker"
export MOONRAKER_CONF="$HOME/printer_data/config/moonraker.conf"
export PRINTER_CFG="$HOME/printer_data/config/printer.cfg"
export ACE_CC_ROOT="$HOME/blocked-ace-root"
export ACE_CC_STATE_DIR="$HOME/.local/share/ace-pro-control-center"
export ACE_CC_SKIP_DEPENDENCIES=1

fail() {
  printf 'FAIL: %s\nTest root: %s\n' "$1" "$TEST_ROOT" >&2
  exit 1
}

mkdir -p "$FLUIDD_ROOT" "$KLIPPER_ROOT/klippy/extras" "$MOONRAKER_ROOT/moonraker/components"
mkdir -p "$(dirname -- "$MOONRAKER_CONF")"
printf '%s\n' 'original-fluidd-after-failure' > "$FLUIDD_ROOT/index.html"
printf '%s\n' 'v1.37.2' > "$FLUIDD_ROOT/.version"
printf '%s\n' 'v0.9.3' > "$MOONRAKER_ROOT/.version"
printf '%s\n' '[server]' > "$MOONRAKER_CONF"
printf '%s\n' '[printer]' > "$PRINTER_CFG"
printf '%s\n' 'this file intentionally blocks mkdir' > "$ACE_CC_ROOT"

fake_bin="$TEST_ROOT/bin"
mkdir -p "$fake_bin"
printf '%s\n' '#!/usr/bin/env sh' "printf '200'" > "$fake_bin/curl"
printf '%s\n' '#!/usr/bin/env sh' 'exit 0' > "$fake_bin/sha256sum"
printf '%s\n' '#!/usr/bin/env sh' "[ \"\${1:-}\" = '-u' ] && printf '1000\\n'" > "$fake_bin/id"
chmod +x "$fake_bin/curl" "$fake_bin/sha256sum" "$fake_bin/id"
export PATH="$fake_bin:$PATH"

export ACE_CC_TEST_FAIL_ARCHIVE_AT=2
if sh "$ROOT_DIR/ui-installer.sh" --yes --install; then
  fail "installation should fail when archive fault injection triggers"
fi
unset ACE_CC_TEST_FAIL_ARCHIVE_AT
grep -Fq 'original-fluidd-after-failure' "$FLUIDD_ROOT/index.html" || fail 'archive failure changed Fluidd'
grep -Fq '[server]' "$MOONRAKER_CONF" || fail 'archive failure changed moonraker.conf'
grep -Fq '[printer]' "$PRINTER_CFG" || fail 'archive failure changed printer.cfg'
[ -f "$ACE_CC_ROOT" ] || fail 'archive failure changed blocking ACE_CC_ROOT file'
[ ! -e "$ACE_CC_STATE_DIR/installed" ] || fail 'archive failure created an install marker'
if find "$ACE_CC_STATE_DIR/old" -type f -name archive.complete -print -quit | grep -q .; then
  fail 'injected partial archive must not be marked complete'
fi

if sh "$ROOT_DIR/ui-installer.sh" --yes --install; then
  fail "installation should fail when ACE_CC_ROOT is a regular file"
fi

grep -Fq 'original-fluidd-after-failure' "$FLUIDD_ROOT/index.html" || fail 'Fluidd was not restored'
grep -Fq '[server]' "$MOONRAKER_CONF" || fail 'moonraker.conf was not restored'
grep -Fq '[printer]' "$PRINTER_CFG" || fail 'printer.cfg was not restored'
[ -f "$ACE_CC_ROOT" ] || fail 'blocking ACE_CC_ROOT file was altered'
find "$ACE_CC_STATE_DIR/old" -type d -name 'install-failure-quarantine-*' -print -quit | grep -q . || fail 'failure quarantine missing'

prepare_overlap_source() {
  source_root=$1
  mkdir -p "$source_root/extras" "$source_root/fluidd-dist" \
    "$source_root/ace_status_integration/moonraker" "$source_root/ace_status_integration/web"
  cp "$ROOT_DIR/ui-installer.sh" "$source_root/ui-installer.sh"
  cp "$ROOT_DIR/VERSION" "$source_root/VERSION"
  cp "$ROOT_DIR/manifest.sha256" "$source_root/manifest.sha256"
  cp "$ROOT_DIR/extras/ace.py" "$source_root/extras/ace.py"
  cp "$ROOT_DIR/ace.cfg" "$source_root/ace.cfg"
  cp "$ROOT_DIR/requirements.txt" "$source_root/requirements.txt"
  cp "$ROOT_DIR/fluidd-dist/index.html" "$source_root/fluidd-dist/index.html"
  cp "$ROOT_DIR/ace_status_integration/moonraker/ace_status.py" \
    "$source_root/ace_status_integration/moonraker/ace_status.py"
  cp "$ROOT_DIR/ace_status_integration/web/ace.html" \
    "$source_root/ace_status_integration/web/ace.html"
}

run_overlap_case() {
  label=$1; action=$2; relation=$3
  case_root="$TEST_ROOT/overlap-$label"
  case "$relation" in
    same) source_root="$case_root/source"; runtime_root="$source_root" ;;
    target_inside_source) source_root="$case_root/source"; runtime_root="$source_root/runtime" ;;
    source_inside_target) runtime_root="$case_root/runtime"; source_root="$runtime_root/source" ;;
    *) fail "unknown overlap relation: $relation" ;;
  esac
  prepare_overlap_source "$source_root"

  case_home="$case_root/home"
  case_fluidd="$case_home/fluidd"
  case_klipper="$case_home/klipper"
  case_moonraker="$case_home/moonraker"
  case_config="$case_home/printer_data/config"
  case_state="$case_home/.local/share/ace-pro-control-center"
  mkdir -p "$case_fluidd" "$case_klipper/klippy/extras" \
    "$case_moonraker/moonraker/components" "$case_config"
  printf '%s\n' 'overlap-fluidd-sentinel' > "$case_fluidd/index.html"
  printf '%s\n' 'v1.37.2' > "$case_fluidd/.version"
  printf '%s\n' 'overlap-klipper-sentinel' > "$case_klipper/klippy/extras/ace.py"
  printf '%s\n' 'v0.9.3' > "$case_moonraker/.version"
  printf '%s\n' '[server] # overlap-moonraker-sentinel' > "$case_config/moonraker.conf"
  printf '%s\n' '[printer] # overlap-printer-sentinel' > "$case_config/printer.cfg"
  payload_checksum=$(cksum "$source_root/extras/ace.py")
  overlap_log="$case_root/output.log"

  if env HOME="$case_home" FLUIDD_ROOT="$case_fluidd" KLIPPER_ROOT="$case_klipper" \
    MOONRAKER_ROOT="$case_moonraker" MOONRAKER_CONF="$case_config/moonraker.conf" \
    PRINTER_CFG="$case_config/printer.cfg" ACE_CC_ROOT="$runtime_root" \
    ACE_CC_STATE_DIR="$case_state" ACE_CC_SKIP_DEPENDENCIES=1 ACE_CC_LANG=en-US \
    sh "$source_root/ui-installer.sh" --yes "$action" >"$overlap_log" 2>&1; then
    fail "overlapping source/runtime paths must reject $action ($relation)"
  fi

  grep -Fq 'identical or contain one another' "$overlap_log" || fail "overlap error missing: $label"
  grep -Fq 'overlap-fluidd-sentinel' "$case_fluidd/index.html" || fail "overlap moved Fluidd: $label"
  grep -Fq 'overlap-klipper-sentinel' "$case_klipper/klippy/extras/ace.py" || fail "overlap moved Klipper target: $label"
  grep -Fq 'overlap-moonraker-sentinel' "$case_config/moonraker.conf" || fail "overlap changed Moonraker config: $label"
  grep -Fq 'overlap-printer-sentinel' "$case_config/printer.cfg" || fail "overlap changed printer.cfg: $label"
  [ "$(cksum "$source_root/extras/ace.py")" = "$payload_checksum" ] || fail "overlap moved source payload: $label"
  [ ! -e "$case_state/old" ] || fail "overlap created an archive: $label"
}

run_overlap_case all-same --install same
run_overlap_case driver-target-inside --install-driver target_inside_source
run_overlap_case card-source-inside --install-card source_inside_target
run_overlap_case rollback-same --rollback-latest same
run_overlap_case uninstall-source-inside --uninstall source_inside_target

printf 'PASS: failed installation recovery and source/runtime overlap rejection\nTest root retained at: %s\n' "$TEST_ROOT"
