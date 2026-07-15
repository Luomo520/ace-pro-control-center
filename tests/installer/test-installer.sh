#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR=$(CDPATH= cd -- "$(dirname -- "$0")/../.." && pwd)
TEST_ROOT=$(mktemp -d "${TMPDIR:-/tmp}/aceprosv08-installer.XXXXXX")
export HOME="$TEST_ROOT/home"
export FLUIDD_ROOT="$HOME/fluidd"
export MOONRAKER_ROOT="$HOME/moonraker"
export MOONRAKER_CONF="$HOME/printer_data/config/moonraker.conf"
export ACEPRO_ROOT="$HOME/ACEPROSV08"
export ACEPROSV08_UI_STATE_DIR="$HOME/.local/share/aceprosv08-ui"

fail() {
  printf 'FAIL: %s\nTest root: %s\n' "$1" "$TEST_ROOT" >&2
  exit 1
}

assert_file() {
  [ -f "$1" ] || fail "missing file: $1"
}

assert_absent() {
  [ ! -e "$1" ] || fail "path should be absent: $1"
}

assert_contains() {
  grep -Fq "$2" "$1" || fail "$1 does not contain: $2"
}

assert_not_contains() {
  if grep -Fq "$2" "$1"; then
    fail "$1 unexpectedly contains: $2"
  fi
}

assert_web_readable() {
  if find "$FLUIDD_ROOT" -type d ! -perm -005 -print -quit | grep -q .; then
    fail "Fluidd directory is not readable/traversable by the web server"
  fi
  if find "$FLUIDD_ROOT" -type f ! -perm -004 -print -quit | grep -q .; then
    fail "Fluidd file is not readable by the web server"
  fi
}

mkdir -p "$FLUIDD_ROOT" "$MOONRAKER_ROOT/moonraker/components"
mkdir -p "$(dirname -- "$MOONRAKER_CONF")" "$ACEPRO_ROOT/extras"
printf '%s\n' 'original-fluidd' > "$FLUIDD_ROOT/index.html"
printf '%s\n' '{"moonrakerInstances":[]}' > "$FLUIDD_ROOT/config.json"
printf '%s\n' '[server]' > "$MOONRAKER_CONF"
printf '%s\n' '# simulated ACEPROSV08 driver' > "$ACEPRO_ROOT/extras/ace.py"
chmod -R u+rwX,go-rX "$FLUIDD_ROOT"

fake_bin="$TEST_ROOT/bin"
mkdir -p "$fake_bin"
printf '%s\n' '#!/usr/bin/env sh' "printf '200'" > "$fake_bin/curl"
chmod +x "$fake_bin/curl"
export PATH="$fake_bin:$PATH"

sh "$ROOT_DIR/ui-installer.sh" --yes --install
assert_file "$ACEPROSV08_UI_STATE_DIR/installed"
assert_file "$ACEPROSV08_UI_STATE_DIR/first_install_backup"
assert_file "$MOONRAKER_ROOT/moonraker/components/ace_status.py"
assert_file "$ACEPRO_ROOT/ace_status_integration/web/ace.html"
assert_contains "$MOONRAKER_CONF" '[ace_status]'
assert_contains "$FLUIDD_ROOT/index.html" '<!DOCTYPE html>'
assert_web_readable

first_backup_count=$(find "$ACEPROSV08_UI_STATE_DIR/backups" -mindepth 1 -maxdepth 1 -type d | wc -l)
[ "$first_backup_count" -eq 1 ] || fail "normal install should create one backup"

sh "$ROOT_DIR/ui-installer.sh" --yes --install-force
second_backup_count=$(find "$ACEPROSV08_UI_STATE_DIR/backups" -mindepth 1 -maxdepth 1 -type d | wc -l)
[ "$second_backup_count" -eq 2 ] || fail "forced update should create another backup"

sh "$ROOT_DIR/ui-installer.sh" --yes --uninstall
third_backup_count=$(find "$ACEPROSV08_UI_STATE_DIR/backups" -mindepth 1 -maxdepth 1 -type d | wc -l)
[ "$third_backup_count" -eq 3 ] || fail "uninstall should create a backup"
assert_contains "$FLUIDD_ROOT/index.html" 'original-fluidd'
assert_contains "$FLUIDD_ROOT/config.json" 'moonrakerInstances'
assert_web_readable
assert_not_contains "$MOONRAKER_CONF" '[ace_status]'
assert_absent "$MOONRAKER_ROOT/moonraker/components/ace_status.py"
assert_absent "$ACEPRO_ROOT/ace_status_integration/web"

printf 'PASS: installer transaction and restore checks\nTest root retained at: %s\n' "$TEST_ROOT"
