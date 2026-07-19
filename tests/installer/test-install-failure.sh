#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR=$(CDPATH= cd -- "$(dirname -- "$0")/../.." && pwd)
TEST_ROOT=$(mktemp -d "${TMPDIR:-/tmp}/aceprosv08-installer-failure.XXXXXX")
export HOME="$TEST_ROOT/home"
export FLUIDD_ROOT="$HOME/fluidd"
export KLIPPER_ROOT="$HOME/klipper"
export MOONRAKER_ROOT="$HOME/moonraker"
export MOONRAKER_CONF="$HOME/printer_data/config/moonraker.conf"
export PRINTER_CFG="$HOME/printer_data/config/printer.cfg"
export ACEPRO_ROOT="$HOME/blocked-ace-root"
export ACEPROSV08_UI_STATE_DIR="$HOME/.local/share/aceprosv08-ui"

fail() {
  printf 'FAIL: %s\nTest root: %s\n' "$1" "$TEST_ROOT" >&2
  exit 1
}

mkdir -p "$FLUIDD_ROOT" "$KLIPPER_ROOT/klippy/extras" "$MOONRAKER_ROOT/moonraker/components"
mkdir -p "$(dirname -- "$MOONRAKER_CONF")"
printf '%s\n' 'original-fluidd-after-failure' > "$FLUIDD_ROOT/index.html"
printf '%s\n' 'v1.37.2' > "$FLUIDD_ROOT/.version"
printf '%s\n' '[server]' > "$MOONRAKER_CONF"
printf '%s\n' '[printer]' > "$PRINTER_CFG"
printf '%s\n' 'this file intentionally blocks mkdir' > "$ACEPRO_ROOT"

fake_bin="$TEST_ROOT/bin"
mkdir -p "$fake_bin"
printf '%s\n' '#!/usr/bin/env sh' "printf '200'" > "$fake_bin/curl"
chmod +x "$fake_bin/curl"
export PATH="$fake_bin:$PATH"

if sh "$ROOT_DIR/ui-installer.sh" --yes --install; then
  fail "installation should fail when ACEPRO_ROOT is a regular file"
fi

grep -Fq 'original-fluidd-after-failure' "$FLUIDD_ROOT/index.html" || fail 'Fluidd was not restored'
grep -Fq '[server]' "$MOONRAKER_CONF" || fail 'moonraker.conf was not restored'
grep -Fq '[printer]' "$PRINTER_CFG" || fail 'printer.cfg was not restored'
[ -f "$ACEPRO_ROOT" ] || fail 'blocking ACEPRO_ROOT file was altered'
find "$ACEPROSV08_UI_STATE_DIR/old" -type d -name 'install-failure-quarantine' -print -quit | grep -q . || fail 'failure quarantine missing'

printf 'PASS: failed installation restored all archived files\nTest root retained at: %s\n' "$TEST_ROOT"
