#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR=$(CDPATH= cd -- "$(dirname -- "$0")/../.." && pwd)
TEST_ROOT=$(mktemp -d "${TMPDIR:-/tmp}/ace-control-center-installer-scopes.XXXXXX")
export HOME="$TEST_ROOT/home"
export FLUIDD_ROOT="$HOME/fluidd"
export KLIPPER_ROOT="$HOME/klipper"
export MOONRAKER_ROOT="$HOME/moonraker"
export MOONRAKER_CONF="$HOME/printer_data/config/moonraker.conf"
export PRINTER_CFG="$HOME/printer_data/config/printer.cfg"
export ACE_CC_ROOT="$HOME/ace-pro-control-center"
export ACE_CC_STATE_DIR="$HOME/.local/share/ace-pro-control-center"
export ACE_CC_SKIP_DEPENDENCIES=1
export ACE_CC_UPPER_SENSOR_PIN='^toolboard:PA5'
export ACE_CC_LOWER_SENSOR_PIN='^toolboard:PA6'
export ACE_CC_PARKING_SENSOR=yes
export ACE_CC_PARKING_SENSOR_PIN='^mainboard:PC0'
export ACE_CC_PARKING_SENSOR_POSITION=after_five_way

fail() {
  printf 'FAIL: %s\nTest root: %s\n' "$1" "$TEST_ROOT" >&2
  exit 1
}

assert_contains() { grep -Fq "$2" "$1" || fail "$1 does not contain: $2"; }
assert_absent() { [ ! -e "$1" ] || fail "path should be absent: $1"; }
assert_config_editable() {
  config="$HOME/printer_data/config/ace.cfg"
  [ -f "$config" ] || fail "missing config file: $config"
  [ ! -L "$config" ] || fail "config must not be a symlink: $config"
  [ -w "$config" ] || fail "config must be writable: $config"
}

mkdir -p "$FLUIDD_ROOT" "$KLIPPER_ROOT/klippy/extras" "$MOONRAKER_ROOT/moonraker/components" "$ACE_CC_ROOT/extras"
mkdir -p "$(dirname -- "$MOONRAKER_CONF")"
printf '%s\n' 'original-fluidd-scopes' > "$FLUIDD_ROOT/index.html"
printf '%s\n' 'v2.0.0' > "$FLUIDD_ROOT/.version"
printf '%s\n' '[server]' > "$MOONRAKER_CONF"
printf '%s\n' '[printer]' > "$PRINTER_CFG"
printf '%s\n' '# original scoped driver' > "$ACE_CC_ROOT/extras/ace.py"
ln -s "$ACE_CC_ROOT/extras/ace.py" "$KLIPPER_ROOT/klippy/extras/ace.py"
printf '%s\n' '# legacy config content must survive symlink migration' > "$ACE_CC_ROOT/ace.cfg"
ln -s "$ACE_CC_ROOT/ace.cfg" "$HOME/printer_data/config/ace.cfg"
legacy_config_is_symlink=0
[ ! -L "$HOME/printer_data/config/ace.cfg" ] || legacy_config_is_symlink=1
printf '%s\n' 'v0.9.3' > "$MOONRAKER_ROOT/.version"

fake_bin="$TEST_ROOT/bin"
mkdir -p "$fake_bin"
printf '%s\n' '#!/usr/bin/env sh' "printf '200'" > "$fake_bin/curl"
printf '%s\n' '#!/usr/bin/env sh' 'exit 0' > "$fake_bin/sha256sum"
printf '%s\n' '#!/usr/bin/env sh' "[ \"\${1:-}\" = '-u' ] && printf '1000\\n'" > "$fake_bin/id"
chmod +x "$fake_bin/curl" "$fake_bin/sha256sum" "$fake_bin/id"
export PATH="$fake_bin:$PATH"

if printf 'y\n3\n' | sh "$ROOT_DIR/ui-installer.sh" --install; then
  fail 'interactive complete install should allow compatibility cancellation'
fi
assert_contains "$FLUIDD_ROOT/index.html" 'original-fluidd-scopes'
assert_absent "$ACE_CC_STATE_DIR/old"

printf 'y\n1\n' | sh "$ROOT_DIR/ui-installer.sh" --install
assert_contains "$ACE_CC_ROOT/extras/ace.py" 'ACE_PRO_CONTROL_CENTER_DRIVER_VERSION'
assert_contains "$ACE_CC_ROOT/ace.cfg" 'legacy config content must survive symlink migration'
assert_contains "$HOME/printer_data/config/ace.cfg" 'legacy config content must survive symlink migration'
if grep -Fq 'extruder_sensor_pin: ^toolboard:PA5' "$ACE_CC_ROOT/ace.cfg"; then
  fail 'preserve mode must not rewrite the existing configuration with wizard answers'
fi
assert_contains "$ACE_CC_ROOT/ace.cfg.example" '#extruder_sensor_pin: ^YOUR_TOOLHEAD_MCU_PIN'
assert_contains "$ACE_CC_ROOT/ace.cfg.example" '#toolhead_sensor_pin: ^YOUR_TOOLHEAD_MCU_PIN'
assert_contains "$ACE_CC_ROOT/ace.cfg.example" '#parking_sensor_pin: ^YOUR_MCU_PIN'
if grep -Fq '^toolboard:PA5' "$ACE_CC_ROOT/ace.cfg.example" || grep -Fq '^mainboard:PC0' "$ACE_CC_ROOT/ace.cfg.example"; then
  fail 'preserve mode example must use safe defaults instead of sensor answers'
fi
cmp -s "$ACE_CC_ROOT/ace.cfg" "$HOME/printer_data/config/ace.cfg" || fail 'runtime and project config copies differ'
assert_config_editable
assert_contains "$FLUIDD_ROOT/index.html" 'original-fluidd-scopes'
assert_contains "$MOONRAKER_CONF" '[server]'
assert_absent "$ACE_CC_STATE_DIR/first-install-old-card"

sh "$ROOT_DIR/ui-installer.sh" --yes --uninstall-driver
assert_contains "$ACE_CC_ROOT/extras/ace.py" 'original scoped driver'
if [ "$legacy_config_is_symlink" -eq 1 ]; then
  [ -L "$HOME/printer_data/config/ace.cfg" ] || fail 'driver uninstall should restore the original config symlink'
fi
assert_contains "$HOME/printer_data/config/ace.cfg" 'legacy config content must survive symlink migration'
assert_contains "$FLUIDD_ROOT/index.html" 'original-fluidd-scopes'

if printf 'y\nn\n' | sh "$ROOT_DIR/ui-installer.sh" --install-card; then
  fail 'higher Fluidd version prompt should allow card installation cancellation'
fi
assert_contains "$FLUIDD_ROOT/index.html" 'original-fluidd-scopes'
assert_absent "$ACE_CC_STATE_DIR/first-install-old-card"

printf 'y\ny\n' | sh "$ROOT_DIR/ui-installer.sh" --install-card
assert_contains "$FLUIDD_ROOT/index.html" '<!DOCTYPE html>'
assert_contains "$ACE_CC_ROOT/extras/ace.py" 'original scoped driver'
assert_contains "$MOONRAKER_CONF" '[ace_status]'

sh "$ROOT_DIR/ui-installer.sh" --yes --rollback-latest
assert_contains "$FLUIDD_ROOT/index.html" 'original-fluidd-scopes'
assert_contains "$ACE_CC_ROOT/extras/ace.py" 'original scoped driver'
assert_contains "$MOONRAKER_CONF" '[server]'

sh "$ROOT_DIR/ui-installer.sh" --yes --install-driver
printf '%s\n' 'v1.37.2' > "$FLUIDD_ROOT/.version"
sh "$ROOT_DIR/ui-installer.sh" --yes --install-card
sh "$ROOT_DIR/ui-installer.sh" --yes --uninstall
assert_contains "$ACE_CC_ROOT/extras/ace.py" 'original scoped driver'
assert_contains "$FLUIDD_ROOT/index.html" 'original-fluidd-scopes'
assert_contains "$MOONRAKER_CONF" '[server]'

printf '%s\n' 'v2.0.0' > "$FLUIDD_ROOT/.version"
printf '%s\n' 'v0.9.4' > "$MOONRAKER_ROOT/.version"
printf 'y\n2\n' | sh "$ROOT_DIR/ui-installer.sh" --install
assert_contains "$ACE_CC_ROOT/extras/ace.py" 'ACE_PRO_CONTROL_CENTER_DRIVER_VERSION'
assert_contains "$FLUIDD_ROOT/index.html" '<!DOCTYPE html>'
assert_contains "$MOONRAKER_CONF" '[ace_status]'
sh "$ROOT_DIR/ui-installer.sh" --yes --uninstall

printf 'PASS: scoped installs, rollback, and combined uninstall restore correctly\nTest root retained at: %s\n' "$TEST_ROOT"
