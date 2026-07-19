#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR=$(CDPATH= cd -- "$(dirname -- "$0")/../.." && pwd)
TEST_ROOT=$(mktemp -d "${TMPDIR:-/tmp}/aceprosv08-installer-scopes.XXXXXX")
export HOME="$TEST_ROOT/home"
export FLUIDD_ROOT="$HOME/fluidd"
export KLIPPER_ROOT="$HOME/klipper"
export MOONRAKER_ROOT="$HOME/moonraker"
export MOONRAKER_CONF="$HOME/printer_data/config/moonraker.conf"
export PRINTER_CFG="$HOME/printer_data/config/printer.cfg"
export ACEPRO_ROOT="$HOME/ACEPROSV08"
export ACEPROSV08_UI_STATE_DIR="$HOME/.local/share/aceprosv08-ui"
export ACEPROSV08_SKIP_DEPENDENCIES=1

fail() {
  printf 'FAIL: %s\nTest root: %s\n' "$1" "$TEST_ROOT" >&2
  exit 1
}

assert_contains() { grep -Fq "$2" "$1" || fail "$1 does not contain: $2"; }
assert_absent() { [ ! -e "$1" ] || fail "path should be absent: $1"; }

mkdir -p "$FLUIDD_ROOT" "$KLIPPER_ROOT/klippy/extras" "$MOONRAKER_ROOT/moonraker/components" "$ACEPRO_ROOT/extras"
mkdir -p "$(dirname -- "$MOONRAKER_CONF")"
printf '%s\n' 'original-fluidd-scopes' > "$FLUIDD_ROOT/index.html"
printf '%s\n' 'v2.0.0' > "$FLUIDD_ROOT/.version"
printf '%s\n' '[server]' > "$MOONRAKER_CONF"
printf '%s\n' '[printer]' > "$PRINTER_CFG"
printf '%s\n' '# original scoped driver' > "$ACEPRO_ROOT/extras/ace.py"
ln -s "$ACEPRO_ROOT/extras/ace.py" "$KLIPPER_ROOT/klippy/extras/ace.py"

fake_bin="$TEST_ROOT/bin"
mkdir -p "$fake_bin"
printf '%s\n' '#!/usr/bin/env sh' "printf '200'" > "$fake_bin/curl"
chmod +x "$fake_bin/curl"
export PATH="$fake_bin:$PATH"

sh "$ROOT_DIR/ui-installer.sh" --install-driver
assert_contains "$ACEPRO_ROOT/extras/ace.py" 'ACEPROSV08_DRIVER_VERSION'
assert_contains "$FLUIDD_ROOT/index.html" 'original-fluidd-scopes'
assert_contains "$MOONRAKER_CONF" '[server]'
assert_absent "$ACEPROSV08_UI_STATE_DIR/first_install_old_card"

sh "$ROOT_DIR/ui-installer.sh" --uninstall-driver
assert_contains "$ACEPRO_ROOT/extras/ace.py" 'original scoped driver'
assert_contains "$FLUIDD_ROOT/index.html" 'original-fluidd-scopes'

if printf 'n\n' | sh "$ROOT_DIR/ui-installer.sh" --install-card; then
  fail 'higher Fluidd version prompt should allow card installation cancellation'
fi
assert_contains "$FLUIDD_ROOT/index.html" 'original-fluidd-scopes'
assert_absent "$ACEPROSV08_UI_STATE_DIR/first_install_old_card"

sh "$ROOT_DIR/ui-installer.sh" --yes --install-card
assert_contains "$FLUIDD_ROOT/index.html" '<!DOCTYPE html>'
assert_contains "$ACEPRO_ROOT/extras/ace.py" 'original scoped driver'
assert_contains "$MOONRAKER_CONF" '[ace_status]'

sh "$ROOT_DIR/ui-installer.sh" --yes --rollback-latest
assert_contains "$FLUIDD_ROOT/index.html" 'original-fluidd-scopes'
assert_contains "$ACEPRO_ROOT/extras/ace.py" 'original scoped driver'
assert_contains "$MOONRAKER_CONF" '[server]'

printf 'PASS: driver-only and card-only install scopes are isolated and rollback correctly\nTest root retained at: %s\n' "$TEST_ROOT"
