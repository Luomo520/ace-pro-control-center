#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR=$(CDPATH= cd -- "$(dirname -- "$0")/../.." && pwd)
BASE_PATH=$PATH

fail() {
  printf 'FAIL: %s\nTest root: %s\n' "$1" "${TEST_ROOT:-not-created}" >&2
  exit 1
}

setup_case() {
  label=$1
  TEST_ROOT=$(mktemp -d "${TMPDIR:-/tmp}/ace-control-center-${label}.XXXXXX")
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
  printf '%s\n' 'original-fluidd-transaction' > "$FLUIDD_ROOT/index.html"
  printf '%s\n' 'v1.37.2' > "$FLUIDD_ROOT/.version"
  printf '%s\n' 'v0.9.3' > "$MOONRAKER_ROOT/.version"
  printf '%s\n' '[server]' > "$MOONRAKER_CONF"
  printf '%s\n' '[printer]' > "$PRINTER_CFG"
  printf '%s\n' 'original-driver-root' > "$ACE_CC_ROOT/extras/ace.py"
  ln -s "$ACE_CC_ROOT/extras/ace.py" "$KLIPPER_ROOT/klippy/extras/ace.py"
  printf '%s\n' 'original-project-config' > "$ACE_CC_ROOT/ace.cfg"
  printf '%s\n' 'original-external-config' > "$HOME/legacy/ace.cfg"
  CONFIG_LINK_TARGET='../../legacy/ace.cfg'
  ln -s "$CONFIG_LINK_TARGET" "$HOME/printer_data/config/ace.cfg"
  COMPONENT_LINK_TARGET='../missing/ace_status.py'
  if ! ln -s "$COMPONENT_LINK_TARGET" "$MOONRAKER_ROOT/moonraker/components/ace_status.py" 2>/dev/null; then
    printf '%s\n' 'original-moonraker-component' > "$MOONRAKER_ROOT/moonraker/components/ace_status.py"
  fi
  printf '%s\n' 'original-web' > "$ACE_CC_ROOT/ace_status_integration/web/ace.html"
  DRIVER_WAS_SYMLINK=0
  CONFIG_WAS_SYMLINK=0
  COMPONENT_WAS_SYMLINK=0
  [ ! -L "$KLIPPER_ROOT/klippy/extras/ace.py" ] || DRIVER_WAS_SYMLINK=1
  [ ! -L "$HOME/printer_data/config/ace.cfg" ] || CONFIG_WAS_SYMLINK=1
  [ ! -L "$MOONRAKER_ROOT/moonraker/components/ace_status.py" ] || COMPONENT_WAS_SYMLINK=1
  if [ "$(uname -s)" = Linux ]; then
    [ "$DRIVER_WAS_SYMLINK" = 1 ] || fail 'Linux test requires an absolute driver symlink'
    [ "$CONFIG_WAS_SYMLINK" = 1 ] || fail 'Linux test requires a relative config symlink'
    [ "$COMPONENT_WAS_SYMLINK" = 1 ] || fail 'Linux test requires a dangling component symlink'
  fi
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
  unset ACE_CC_TEST_FAIL_ARCHIVE_AT ACE_CC_TEST_FAIL_ARCHIVE_KEY
  unset ACE_CC_TEST_FAIL_REPLACE_AT ACE_CC_TEST_FAIL_REPLACE_KEY
  unset ACE_CC_TEST_FAIL_RESTORE_AT ACE_CC_TEST_FAIL_RESTORE_KEY
  unset ACE_CC_TEST_SIGNAL_AFTER_REPLACE_AT
}

assert_original() {
  grep -Fq 'original-fluidd-transaction' "$FLUIDD_ROOT/index.html" || fail 'Fluidd changed'
  if [ "$COMPONENT_WAS_SYMLINK" = "1" ]; then
    [ -L "$MOONRAKER_ROOT/moonraker/components/ace_status.py" ] || fail 'dangling component link type changed'
    [ "$(readlink "$MOONRAKER_ROOT/moonraker/components/ace_status.py")" = "$COMPONENT_LINK_TARGET" ] || fail 'dangling component link target changed'
  else
    grep -Fq 'original-moonraker-component' "$MOONRAKER_ROOT/moonraker/components/ace_status.py" || fail 'Moonraker component changed'
  fi
  grep -Fq '[server]' "$MOONRAKER_CONF" || fail 'moonraker.conf changed'
  grep -Fq '[printer]' "$PRINTER_CFG" || fail 'printer.cfg changed'
  grep -Fq 'original-driver-root' "$ACE_CC_ROOT/extras/ace.py" || fail 'driver root changed'
  if [ "$DRIVER_WAS_SYMLINK" = "1" ]; then
    [ -L "$KLIPPER_ROOT/klippy/extras/ace.py" ] || fail 'driver link type changed'
    [ "$(readlink "$KLIPPER_ROOT/klippy/extras/ace.py")" = "$ACE_CC_ROOT/extras/ace.py" ] || fail 'driver link target changed'
  else
    cmp -s "$TEST_ROOT/expected/driver-link" "$KLIPPER_ROOT/klippy/extras/ace.py" || fail 'simulated driver link changed'
  fi
  grep -Fq 'original-project-config' "$ACE_CC_ROOT/ace.cfg" || fail 'project config changed'
  if [ "$CONFIG_WAS_SYMLINK" = "1" ]; then
    [ -L "$HOME/printer_data/config/ace.cfg" ] || fail 'runtime config link type changed'
    [ "$(readlink "$HOME/printer_data/config/ace.cfg")" = "$CONFIG_LINK_TARGET" ] || fail 'relative runtime config link target changed'
  else
    cmp -s "$TEST_ROOT/expected/runtime-config" "$HOME/printer_data/config/ace.cfg" || fail 'simulated runtime link changed'
  fi
  grep -Fq 'original-external-config' "$HOME/legacy/ace.cfg" || fail 'external config content changed'
  grep -Fq 'original-web' "$ACE_CC_ROOT/ace_status_integration/web/ace.html" || fail 'web fallback changed'
  [ ! -e "$ACE_CC_STATE_DIR/installed" ] || fail 'failed transaction left an install marker'
}

setup_case archive-failure
export ACE_CC_TEST_FAIL_ARCHIVE_AT=3
if sh "$ROOT_DIR/ui-installer.sh" --yes --install; then
  fail 'archive failure injection should fail installation'
fi
assert_original
if find "$ACE_CC_STATE_DIR/old" -type f -name archive.complete -print -quit | grep -q .; then
  fail 'partial archive was marked complete'
fi

setup_case replacement-failure
export ACE_CC_TEST_FAIL_REPLACE_KEY=printer-config/printer.cfg
if sh "$ROOT_DIR/ui-installer.sh" --yes --install; then
  fail 'replacement failure injection should fail installation'
fi
assert_original
find "$ACE_CC_STATE_DIR/old" -type d -name 'install-failure-quarantine-*' -print -quit | grep -q . || fail 'installation recovery quarantine missing'

setup_case signal-recovery
export ACE_CC_TEST_SIGNAL_AFTER_REPLACE_AT=2
if sh "$ROOT_DIR/ui-installer.sh" --yes --install; then
  fail 'TERM injection should interrupt installation'
fi
assert_original
find "$ACE_CC_STATE_DIR/old" -type d -name 'exit-143-quarantine-*' -print -quit | grep -q . || fail 'signal recovery quarantine missing'

setup_case restore-failure
export ACE_CC_TEST_FAIL_REPLACE_KEY=printer-config/printer.cfg
export ACE_CC_TEST_FAIL_RESTORE_AT=1
output="$TEST_ROOT/restore-failure.log"
if sh "$ROOT_DIR/ui-installer.sh" --yes --install >"$output" 2>&1; then
  fail 'restore failure injection should fail installation'
fi
grep -Fq 'Transaction recovery failed:' "$output" || fail 'restore failure was not propagated'
grep -Fq 'archive=' "$output" || fail 'restore failure did not report archive path'
grep -Fq 'quarantine=' "$output" || fail 'restore failure did not report quarantine path'

printf 'PASS: archive, replacement, signal, restore, and symlink preservation coverage (native assertions enabled on Linux)\n'
