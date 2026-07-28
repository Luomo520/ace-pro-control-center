#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR=$(CDPATH= cd -- "$(dirname -- "$0")/../.." && pwd)
TEST_ROOT=$(mktemp -d "${TMPDIR:-/tmp}/ace-control-center-installer.XXXXXX")
export HOME="$TEST_ROOT/home"
export FLUIDD_ROOT="$HOME/fluidd"
export KLIPPER_ROOT="$HOME/klipper"
export MOONRAKER_ROOT="$HOME/moonraker"
export MOONRAKER_CONF="$HOME/printer_data/config/moonraker.conf"
export PRINTER_CFG="$HOME/printer_data/config/printer.cfg"
export ACE_CC_ROOT="$HOME/ace-pro-control-center"
export ACE_CC_STATE_DIR="$HOME/.local/share/ace-pro-control-center"
export ACE_CC_SKIP_DEPENDENCIES=1

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

assert_config_editable() {
  config="$HOME/printer_data/config/ace.cfg"
  [ -f "$config" ] || fail "missing config file: $config"
  [ ! -L "$config" ] || fail "config must not be a symlink: $config"
  [ -w "$config" ] || fail "config must be writable: $config"
}

mkdir -p "$FLUIDD_ROOT" "$KLIPPER_ROOT/klippy/extras" "$MOONRAKER_ROOT/moonraker/components"
mkdir -p "$(dirname -- "$MOONRAKER_CONF")" "$ACE_CC_ROOT/extras"
printf '%s\n' 'original-fluidd' > "$FLUIDD_ROOT/index.html"
printf '%s\n' '{"moonrakerInstances":[]}' > "$FLUIDD_ROOT/config.json"
printf '%s\n' '[server]' > "$MOONRAKER_CONF"
printf '%s\n' '[printer]' > "$PRINTER_CFG"
printf '%s\n' '# unrelated pre-existing file' > "$ACE_CC_ROOT/extras/ace.py"
printf '%s\n' 'v0.9.3' > "$MOONRAKER_ROOT/.version"
printf '%s\n' 'v1.36.0' > "$FLUIDD_ROOT/.version"
chmod -R u+rwX,go-rX "$FLUIDD_ROOT"

fake_bin="$TEST_ROOT/bin"
mkdir -p "$fake_bin"
printf '%s\n' '#!/usr/bin/env sh' "printf '200'" > "$fake_bin/curl"
printf '%s\n' '#!/usr/bin/env sh' 'exit 0' > "$fake_bin/sha256sum"
printf '%s\n' '#!/usr/bin/env sh' "[ \"\${1:-}\" = '-u' ] && printf '1000\\n'" > "$fake_bin/id"
chmod +x "$fake_bin/curl" "$fake_bin/sha256sum" "$fake_bin/id"
export PATH="$fake_bin:$PATH"

printf '%s\n' '#!/usr/bin/env sh' "[ \"\${1:-}\" = '-u' ] && printf '0\\n'" > "$fake_bin/id"
sh "$ROOT_DIR/ui-installer.sh" --help >/dev/null || fail '--help must work as root'
sh "$ROOT_DIR/ui-installer.sh" --status >/dev/null || fail '--status must work as root'
for action in --install --rollback-latest --uninstall; do
  root_log="$TEST_ROOT/root-${action#--}.log"
  if sh "$ROOT_DIR/ui-installer.sh" --yes "$action" >"$root_log" 2>&1; then
    fail "root action must be rejected: $action"
  fi
  grep -Fq 'Refusing to install, roll back, or uninstall as root' "$root_log" || fail "root rejection message missing: $action"
done
assert_absent "$ACE_CC_STATE_DIR/old"
printf '%s\n' '#!/usr/bin/env sh' "[ \"\${1:-}\" = '-u' ] && printf '1000\\n'" > "$fake_bin/id"

for config_action in --install --install-driver --install-force; do
  invalid_log="$TEST_ROOT/invalid-config-${config_action#--}.log"
  if ACE_CC_CONFIG_MODE=unsafe sh "$ROOT_DIR/ui-installer.sh" --yes "$config_action" >"$invalid_log" 2>&1; then
    fail "invalid ACE_CC_CONFIG_MODE must reject $config_action"
  fi
  grep -Fq 'must be preserve or replace' "$invalid_log" || fail "invalid config mode message missing: $config_action"
done
assert_contains "$FLUIDD_ROOT/index.html" 'original-fluidd'
assert_contains "$MOONRAKER_CONF" '[server]'
assert_contains "$PRINTER_CFG" '[printer]'
assert_absent "$ACE_CC_STATE_DIR/old"

if printf 'n\n' | sh "$ROOT_DIR/ui-installer.sh" --install; then
  fail 'direct CLI action should allow cancellation before compatibility checks'
fi
if printf 'y\nn\n' | sh "$ROOT_DIR/ui-installer.sh" --install; then
  fail "version compatibility prompt should allow the user to cancel"
fi
assert_contains "$FLUIDD_ROOT/index.html" 'original-fluidd'
assert_absent "$ACE_CC_STATE_DIR/old"
if sh "$ROOT_DIR/ui-installer.sh" --yes --install; then
  fail 'normal non-interactive complete install must fail closed on version risk'
fi
if sh "$ROOT_DIR/ui-installer.sh" --yes --install-card; then
  fail 'normal non-interactive card install must fail closed on version risk'
fi
assert_absent "$ACE_CC_STATE_DIR/old"
printf '%s\n' 'v1.37.2' > "$FLUIDD_ROOT/.version"

for moon_version in v0.9.2 v0.9.4 git-deadbeef; do
  printf '%s\n' "$moon_version" > "$MOONRAKER_ROOT/.version"
  if sh "$ROOT_DIR/ui-installer.sh" --yes --install; then
    fail "normal complete install must fail closed for Moonraker risk: $moon_version"
  fi
  if sh "$ROOT_DIR/ui-installer.sh" --yes --install-card; then
    fail "normal card install must fail closed for Moonraker risk: $moon_version"
  fi
  assert_absent "$ACE_CC_STATE_DIR/old"
done
printf '%s\n' 'v0.9.3' > "$MOONRAKER_ROOT/.version"

sh "$ROOT_DIR/ui-installer.sh" --yes --install
assert_file "$ACE_CC_STATE_DIR/installed"
assert_file "$ACE_CC_STATE_DIR/first-install-old"
assert_file "$MOONRAKER_ROOT/moonraker/components/ace_status.py"
assert_file "$ACE_CC_ROOT/ace_status_integration/web/ace.html"
assert_file "$ACE_CC_ROOT/extras/ace.py"
assert_file "$ACE_CC_ROOT/ace.cfg.example"
assert_file "$ACE_CC_ROOT/ace.cfg"
assert_file "$HOME/klipper/klippy/extras/ace.py"
assert_config_editable
assert_contains "$MOONRAKER_CONF" '[ace_status]'
assert_contains "$PRINTER_CFG" '[include ace.cfg]'
assert_contains "$FLUIDD_ROOT/index.html" '<!DOCTYPE html>'
assert_web_readable

first_backup_count=$(find "$ACE_CC_STATE_DIR/old" -mindepth 1 -maxdepth 1 -type d | wc -l)
[ "$first_backup_count" -eq 1 ] || fail "normal install should create one old archive"
first_old=$(find "$ACE_CC_STATE_DIR/old" -type f -path '*/old/ace-root-driver/ace.py' | wc -l)
[ "$first_old" -ge 1 ] || fail "first install should move the existing driver into old"

printf '%s\n' 'v2.0.0' > "$FLUIDD_ROOT/.version"
printf '%s\n' 'git-force-check' > "$MOONRAKER_ROOT/.version"
sh "$ROOT_DIR/ui-installer.sh" --yes --install-force
second_backup_count=$(find "$ACE_CC_STATE_DIR/old" -mindepth 1 -maxdepth 1 -type d | wc -l)
[ "$second_backup_count" -eq 2 ] || fail "forced update should create another old archive"

sh "$ROOT_DIR/ui-installer.sh" --yes --rollback-latest
rollback_archive_count=$(find "$ACE_CC_STATE_DIR/old" -mindepth 1 -maxdepth 1 -type d | wc -l)
[ "$rollback_archive_count" -eq 3 ] || fail "rollback should archive the current version"

if printf 'n\n' | sh "$ROOT_DIR/uninstall.sh"; then
  fail 'uninstall.sh should preserve interactive cancellation'
fi
assert_file "$ACE_CC_STATE_DIR/installed"
sh "$ROOT_DIR/ui-installer.sh" --yes --uninstall
third_backup_count=$(find "$ACE_CC_STATE_DIR/old" -mindepth 1 -maxdepth 1 -type d | wc -l)
[ "$third_backup_count" -eq 4 ] || fail "uninstall should create an old archive"
assert_contains "$FLUIDD_ROOT/index.html" 'original-fluidd'
assert_contains "$FLUIDD_ROOT/config.json" 'moonrakerInstances'
assert_web_readable
assert_not_contains "$MOONRAKER_CONF" '[ace_status]'
assert_absent "$MOONRAKER_ROOT/moonraker/components/ace_status.py"
assert_absent "$ACE_CC_ROOT/ace_status_integration/web"
assert_contains "$ACE_CC_ROOT/extras/ace.py" 'unrelated pre-existing file'
assert_absent "$ACE_CC_ROOT/ace.cfg"
assert_absent "$HOME/printer_data/config/ace.cfg"

printf 'PASS: installer transaction and restore checks\nTest root retained at: %s\n' "$TEST_ROOT"
