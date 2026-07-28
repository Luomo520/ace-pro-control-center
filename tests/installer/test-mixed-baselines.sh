#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR=$(CDPATH= cd -- "$(dirname -- "$0")/../.." && pwd)
BASE_PATH=$PATH

fail() {
  printf 'FAIL: %s\nTest root: %s\n' "$1" "${TEST_ROOT:-not-created}" >&2
  exit 1
}

install_scope() {
  case "$1" in
    all) sh "$ROOT_DIR/ui-installer.sh" --yes --install ;;
    driver) sh "$ROOT_DIR/ui-installer.sh" --yes --install-driver ;;
    card) sh "$ROOT_DIR/ui-installer.sh" --yes --install-card ;;
    *) fail "unknown scope: $1" ;;
  esac
}

setup_case() {
  label=$1
  TEST_ROOT=$(mktemp -d "${TMPDIR:-/tmp}/ace-control-center-baseline-${label}.XXXXXX")
  export HOME="$TEST_ROOT/home"
  export FLUIDD_ROOT="$HOME/fluidd"
  export KLIPPER_ROOT="$HOME/klipper"
  export MOONRAKER_ROOT="$HOME/moonraker"
  export MOONRAKER_CONF="$HOME/printer_data/config/moonraker.conf"
  export PRINTER_CFG="$HOME/printer_data/config/printer.cfg"
  export ACE_CC_ROOT="$HOME/ace-pro-control-center"
  export ACE_CC_STATE_DIR="$HOME/.local/share/ace-pro-control-center"
  export ACE_CC_SKIP_DEPENDENCIES=1
  export ACE_CC_LANG=en-US
  export ACE_CC_UPPER_SENSOR_PIN='^toolboard:PA5'
  export ACE_CC_LOWER_SENSOR_PIN='^toolboard:PA6'

  mkdir -p "$FLUIDD_ROOT" "$KLIPPER_ROOT/klippy/extras" "$MOONRAKER_ROOT/moonraker/components"
  mkdir -p "$(dirname -- "$MOONRAKER_CONF")" "$ACE_CC_ROOT/extras" "$ACE_CC_ROOT/ace_status_integration/web" "$HOME/legacy"
  printf '%s\n' 'baseline-fluidd' > "$FLUIDD_ROOT/index.html"
  printf '%s\n' 'v1.37.2' > "$FLUIDD_ROOT/.version"
  printf '%s\n' 'v0.9.3' > "$MOONRAKER_ROOT/.version"
  printf '%s\n' 'baseline-component' > "$MOONRAKER_ROOT/moonraker/components/ace_status.py"
  printf '%s\n' '[server]' > "$MOONRAKER_CONF"
  printf '%s\n' '[printer]' > "$PRINTER_CFG"
  printf '%s\n' 'baseline-driver-root' > "$ACE_CC_ROOT/extras/ace.py"
  ln -s "$ACE_CC_ROOT/extras/ace.py" "$KLIPPER_ROOT/klippy/extras/ace.py"
  printf '%s\n' 'baseline-project-config' > "$ACE_CC_ROOT/ace.cfg"
  printf '%s\n' 'baseline-external-config' > "$HOME/legacy/ace.cfg"
  ln -s "$HOME/legacy/ace.cfg" "$HOME/printer_data/config/ace.cfg"
  printf '%s\n' 'baseline-web' > "$ACE_CC_ROOT/ace_status_integration/web/ace.html"
  DRIVER_WAS_SYMLINK=0
  CONFIG_WAS_SYMLINK=0
  [ ! -L "$KLIPPER_ROOT/klippy/extras/ace.py" ] || DRIVER_WAS_SYMLINK=1
  [ ! -L "$HOME/printer_data/config/ace.cfg" ] || CONFIG_WAS_SYMLINK=1
  mkdir -p "$TEST_ROOT/expected"
  cp -a "$KLIPPER_ROOT/klippy/extras/ace.py" "$TEST_ROOT/expected/driver-link"
  cp -a "$HOME/printer_data/config/ace.cfg" "$TEST_ROOT/expected/runtime-config"

  fake_bin="$TEST_ROOT/bin"
  mkdir -p "$fake_bin"
  printf '%s\n' '#!/usr/bin/env sh' "printf '200'" > "$fake_bin/curl"
  printf '%s\n' '#!/usr/bin/env sh' 'exit 0' > "$fake_bin/sha256sum"
  printf '%s\n' '#!/usr/bin/env sh' "[ \"\${1:-}\" = '-u' ] && printf '1000\\n'" > "$fake_bin/id"
  chmod +x "$fake_bin/curl" "$fake_bin/sha256sum" "$fake_bin/id"
  export PATH="$fake_bin:$BASE_PATH"
}

assert_first_state() {
  grep -Fq 'baseline-fluidd' "$FLUIDD_ROOT/index.html" || fail 'Fluidd baseline not restored'
  grep -Fq 'baseline-component' "$MOONRAKER_ROOT/moonraker/components/ace_status.py" || fail 'Moonraker component baseline not restored'
  grep -Fq '[server]' "$MOONRAKER_CONF" || fail 'moonraker.conf baseline not restored'
  grep -Fq '[printer]' "$PRINTER_CFG" || fail 'printer.cfg baseline not restored'
  grep -Fq 'baseline-driver-root' "$ACE_CC_ROOT/extras/ace.py" || fail 'driver baseline not restored'
  if [ "$DRIVER_WAS_SYMLINK" = "1" ]; then
    [ -L "$KLIPPER_ROOT/klippy/extras/ace.py" ] || fail 'driver symlink type not restored'
    [ "$(readlink "$KLIPPER_ROOT/klippy/extras/ace.py")" = "$ACE_CC_ROOT/extras/ace.py" ] || fail 'driver symlink target not restored'
  else
    cmp -s "$TEST_ROOT/expected/driver-link" "$KLIPPER_ROOT/klippy/extras/ace.py" || fail 'simulated driver link not restored'
  fi
  grep -Fq 'baseline-project-config' "$ACE_CC_ROOT/ace.cfg" || fail 'project config baseline not restored'
  if [ "$CONFIG_WAS_SYMLINK" = "1" ]; then
    [ -L "$HOME/printer_data/config/ace.cfg" ] || fail 'runtime config symlink type not restored'
    [ "$(readlink "$HOME/printer_data/config/ace.cfg")" = "$HOME/legacy/ace.cfg" ] || fail 'runtime config symlink target not restored'
  else
    cmp -s "$TEST_ROOT/expected/runtime-config" "$HOME/printer_data/config/ace.cfg" || fail 'simulated runtime link not restored'
  fi
  grep -Fq 'baseline-external-config' "$HOME/legacy/ace.cfg" || fail 'external config baseline changed'
  grep -Fq 'baseline-web' "$ACE_CC_ROOT/ace_status_integration/web/ace.html" || fail 'web baseline not restored'
  [ ! -e "$ACE_CC_STATE_DIR/installed" ] || fail 'complete uninstall left install marker'
}

run_order() {
  first=$1; second=$2
  setup_case "$first-$second"
  install_scope "$first"
  [ -s "$ACE_CC_STATE_DIR/first-install-old" ] || fail 'global first-install baseline missing'
  baseline=$(sed -n '1p' "$ACE_CC_STATE_DIR/first-install-old")
  [ -f "$baseline/archive.complete" ] || fail 'global first-install baseline is incomplete'
  [ "$(sed -n 's/^scope=//p' "$baseline/manifest.txt")" = all ] || fail 'global baseline is not all scope'
  install_scope "$second"
  [ "$(sed -n '1p' "$ACE_CC_STATE_DIR/first-install-old")" = "$baseline" ] || fail 'global first-install baseline was overwritten'
  sh "$ROOT_DIR/ui-installer.sh" --yes --uninstall
  assert_first_state
}

run_order driver all
run_order all driver
run_order card all
run_order all card
run_order driver card
run_order card driver

run_full_component_uninstall() {
  scope=$1
  setup_case "full-uninstall-$scope"
  install_scope all
  [ -s "$ACE_CC_STATE_DIR/first-install-old-driver" ] || fail 'full install did not create driver baseline pointer'
  [ -s "$ACE_CC_STATE_DIR/first-install-old-card" ] || fail 'full install did not create card baseline pointer'

  sh "$ROOT_DIR/ui-installer.sh" --yes "--uninstall-$scope"
  [ -s "$ACE_CC_STATE_DIR/installed" ] || fail "scoped $scope uninstall removed the operation marker"
  if [ "$scope" = driver ]; then
    grep -Fq 'baseline-driver-root' "$ACE_CC_ROOT/extras/ace.py" || fail 'driver baseline was not restored from full install'
    grep -Fq '<!DOCTYPE html>' "$FLUIDD_ROOT/index.html" || fail 'driver uninstall changed the installed Fluidd card'
    grep -Fq '[ace_status]' "$MOONRAKER_CONF" || fail 'driver uninstall changed Moonraker card integration'
    grep -Fq 'baseline-external-config' "$HOME/printer_data/config/ace.cfg" || fail 'driver uninstall did not restore runtime config baseline'
  else
    grep -Fq 'baseline-fluidd' "$FLUIDD_ROOT/index.html" || fail 'card baseline was not restored from full install'
    grep -Fq 'baseline-component' "$MOONRAKER_ROOT/moonraker/components/ace_status.py" || fail 'card uninstall did not restore Moonraker component baseline'
    grep -Fq '[server]' "$MOONRAKER_CONF" || fail 'card uninstall did not restore moonraker.conf baseline'
    grep -Fq 'ACE_PRO_CONTROL_CENTER_DRIVER_VERSION' "$ACE_CC_ROOT/extras/ace.py" || fail 'card uninstall changed the installed driver'
    grep -Fq '[include ace.cfg]' "$PRINTER_CFG" || fail 'card uninstall changed printer.cfg driver include'
  fi

  sh "$ROOT_DIR/ui-installer.sh" --yes --rollback-latest
  grep -Fq 'ACE_PRO_CONTROL_CENTER_DRIVER_VERSION' "$ACE_CC_ROOT/extras/ace.py" || fail "rollback did not restore driver after scoped $scope uninstall"
  grep -Fq '<!DOCTYPE html>' "$FLUIDD_ROOT/index.html" || fail "rollback did not restore card after scoped $scope uninstall"
}

run_full_component_uninstall driver
run_full_component_uninstall card

printf 'PASS: mixed install orders restore the global first-write baseline\n'
