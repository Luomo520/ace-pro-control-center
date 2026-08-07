#!/usr/bin/env bash
set -Eeuo pipefail

SCRIPT_DIR=$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd -P)
PROJECT=$(cd -- "$SCRIPT_DIR/.." && pwd -P)
declare -ar KLIPPER_WRAPPERS=(ace_hardware ace_device ace_machine ace_encoder)
if ! python3 --version >/dev/null 2>&1 && python --version >/dev/null 2>&1; then
    export PYTHON_BIN=python
fi
TEMP=$(mktemp -d "${TMPDIR:-/tmp}/ace-v3-installer-test.XXXXXX")
trap 'rm -rf -- "$TEMP"' EXIT

fail() { printf 'FAIL: %s\n' "$*" >&2; exit 1; }
assert_file_contains() { grep -Fq -- "$2" "$1" || fail "$1 lacks: $2"; }

assert_wrapper_links() {
    local repo=$1 root=$2 wrapper link
    for wrapper in "${KLIPPER_WRAPPERS[@]}"; do
        link=$root/home/pi/klipper/klippy/extras/$wrapper.py
        [ -L "$link" ] || fail "$wrapper wrapper link missing"
        [ "$(readlink "$link")" = "$repo/klipper_extras/$wrapper.py" ] ||
            fail "$wrapper wrapper link target is wrong"
    done
}

assert_wrappers_absent() {
    local root=$1 wrapper
    for wrapper in "${KLIPPER_WRAPPERS[@]}"; do
        [ ! -e "$root/home/pi/klipper/klippy/extras/$wrapper.py" ] ||
            fail "$wrapper wrapper should be absent"
    done
}

make_fixture() {
    local repo=$1 root=$2 fluidd_version=${3:-1.37.2}
    mkdir -p "$repo" "$root/home/pi/klipper/klippy/extras"
    mkdir -p "$root/home/pi/moonraker/moonraker/components"
    mkdir -p "$root/home/pi/printer_data/config" "$root/home/pi/fluidd"
    mkdir -p "$root/home/pi/fluidd-src/src/components/layout"
    mkdir -p "$root/home/pi/fluidd-src/src/components/widgets/toolhead"
    mkdir -p "$root/home/pi/fluidd-src/src/views" "$root/home/pi/fluidd-src/src/store/layout"
    mkdir -p "$root/home/pi/fluidd-src/src/router"
    cp -R "$PROJECT/config" "$PROJECT/installer" "$PROJECT/scripts" "$repo/"
    mkdir -p "$repo/ace_driver" "$repo/klipper_extras" "$repo/moonraker"
    mkdir -p "$repo/frontend"
    cp -R "$PROJECT/frontend/dashboard" "$PROJECT/frontend/shared" \
        "$PROJECT/frontend/fluidd-overlay" "$repo/frontend/"
    cp -- "$repo/frontend/shared/ace-core.js" \
        "$repo/frontend/fluidd-overlay/src/components/widgets/ace-v3/ace-core.js"
    printf '%s\n' 'def load_config(config):' '    return object()' > "$repo/ace_driver/__init__.py"
    printf '%s\n' 'def load_config(config):' '    return object()' > "$repo/klipper_extras/ace_hardware.py"
    printf '%s\n' 'def load_config_prefix(config):' '    return object()' > "$repo/klipper_extras/ace_device.py"
    printf '%s\n' 'def load_config(config):' '    return object()' > "$repo/klipper_extras/ace_machine.py"
    printf '%s\n' 'def load_config_prefix(config):' '    return object()' > "$repo/klipper_extras/ace_encoder.py"
    printf '%s\n' 'def load_component(config):' '    return object()' > "$repo/moonraker/ace_status.py"
    cat > "$root/home/pi/klipper/klippy/klippy.py" <<'EOF'
class Printer:
    def get_reactor(self): pass
    def lookup_object(self): pass
    def register_event_handler(self): pass
    def add_object(self): pass
    def load_object(self): pass
    def get_start_args(self): pass
EOF
    cat > "$root/home/pi/klipper/klippy/configfile.py" <<'EOF'
class ConfigWrapper:
    def __init__(self): self.fileconfig = None
    def get_printer(self): pass
    def get_name(self): pass
    def get(self): pass
    def getsection(self): pass
    def get_prefix_sections(self): pass
EOF
    cat > "$root/home/pi/klipper/klippy/reactor.py" <<'EOF'
class Reactor:
    def __init__(self): self.monotonic = lambda: 0.0
    def register_timer(self): pass
    def unregister_timer(self): pass
    def pause(self): pass
EOF
    cat > "$root/home/pi/klipper/klippy/gcode.py" <<'EOF'
class GCodeDispatch:
    def register_command(self): pass
    def run_script_from_command(self): pass
EOF
    cat > "$root/home/pi/klipper/klippy/extras/filament_switch_sensor.py" <<'EOF'
def load_config_prefix(config): pass
class Sensor:
    def get_status(self): pass
EOF
    cat > "$root/home/pi/klipper/klippy/extras/print_stats.py" <<'EOF'
def load_config(config): pass
class PrintStats:
    def get_status(self): pass
EOF
    printf '%s\n' \
        '{' \
        '  "name": "fluidd",' \
        "  \"version\": \"$fluidd_version\"," \
        '  "packageManager": "pnpm@9.15.4",' \
        '  "scripts": {"build": "vite build"},' \
        '  "dependencies": {' \
        '    "vue": "^2.7.16",' \
        '    "vue-router": "^3.6.5",' \
        '    "vuetify": "^2.7.2",' \
        '    "vue-property-decorator": "^9.1.2"' \
        '  }' \
        '}' > "$root/home/pi/fluidd-src/package.json"
    printf '%s\n' \
        '[virtual_sdcard]' \
        'path: ~/gcodes' \
        '' \
        '#*# <---------------------- SAVE_CONFIG ---------------------->' \
        '#*# DO NOT EDIT THIS BLOCK OR BELOW. The contents are auto-generated.' \
        '#*# [bed_mesh default]' \
        '#*# version = 1' > "$root/home/pi/printer_data/config/printer.cfg"
    printf '%s\n' '[server]' 'host: 0.0.0.0' > "$root/home/pi/printer_data/config/moonraker.conf"
    printf '%s\n' 'original-v2-ace-page' > "$root/home/pi/fluidd-src/src/views/AcePro.vue"
    cat > "$root/home/pi/fluidd-src/src/views/Dashboard.vue" <<'EOF'
<template><div /></template>
<script lang="ts">
import { Component, Vue } from 'vue-property-decorator'
import AfcCard from '@/components/widgets/afc/AfcCard.vue'
import type Sortable from 'sortablejs'

@Component({
  components: {
    AfcCard,
  },
})
export default class Dashboard extends Vue {}
</script>
EOF
    cat > "$root/home/pi/fluidd-src/src/components/widgets/toolhead/ToolChangeCommands.vue" <<'EOF'
<template>
      <app-btn-group
        class="app-toolchanger-control d-flex"
        :class="{
          [$vuetify.theme.dark ? 'theme--dark': 'theme--light']: true,
        }"
      />
</template>

<script lang="ts">
import { chunk } from 'lodash-es'
import type { GcodeCommands } from '@/store/printer/types'

export default class ToolChangeCommands {
  get availableCommands (): GcodeCommands {
    return {}
  }

  get toolChangeCommandsGrouped () {
    const toolChangeCommands = this.toolChangeCommands
    const cols = Math.ceil(toolChangeCommands.length / Math.ceil(toolChangeCommands.length / 6))
    return chunk(toolChangeCommands, cols)
  }
}
</script>

<style lang="scss" scoped>
</style>
EOF
    printf '%s\n' "          { id: 'mmu-card', enabled: true, collapsed: false }," > "$root/home/pi/fluidd-src/src/store/layout/state.ts"
    printf '%s\n' \
        'const routes = [' \
        '  {' \
        "    path: '/configure'," \
        "    name: 'configure'," \
        '  },' \
        '  {' \
        "    path: '/acepro'," \
        "    name: 'acepro'," \
        "    component: () => import('@/views/AcePro.vue')," \
        '    ...defaultRouteConfig' \
        '  },' \
        '  {' \
        "    path: '/settings'," \
        "    name: 'settings'," \
        '  }' \
        ']' > "$root/home/pi/fluidd-src/src/router/index.ts"
    printf '%s\n' \
        '<template>' \
        '  <div>' \
        '          <app-nav-item' \
        '            icon="$codeJson"' \
        '            to="configure"' \
        '          >' \
        '            Configure' \
        '          </app-nav-item>' \
        '          <app-nav-item' \
        '            v-if="supportsAcePro"' \
        '            icon="$mmu"' \
        '            to="acepro"' \
        '          >' \
        '            ACE Pro' \
        '          </app-nav-item>' \
        '          <app-nav-item' \
        '            icon="$desktopTower"' \
        '            to="system"' \
        '          >' \
        '            System' \
        '          </app-nav-item>' \
        '  </div>' \
        '</template>' > "$root/home/pi/fluidd-src/src/components/layout/AppNavDrawer.vue"
}

run_installer() {
    local repo=$1 root=$2; shift 2
    bash "$repo/installer/install.sh" \
        --repo "$repo" --root "$root" --home /home/pi \
        --fluidd-source /home/pi/fluidd-src "$@"
}

case "${OSTYPE:-}" in
    msys*|cygwin*)
        if [ "${ACE_TEST_FORCE_FULL:-0}" != 1 ]; then
            DRY_REPO=$TEMP/dry-repo
            DRY_ROOT=$TEMP/dry-root
            make_fixture "$DRY_REPO" "$DRY_ROOT"
            run_installer "$DRY_REPO" "$DRY_ROOT" --dry-run --non-interactive \
                --device-count 2 \
                --device 'ace1|/dev/serial/by-id/dry-one' \
                --device 'ace2|/dev/serial/by-id/dry-two|bus0|uid-dry-two'
            [ ! -e "$DRY_ROOT/home/pi/klipper/klippy/extras/ace" ] || fail 'dry-run created package link'
            assert_wrappers_absent "$DRY_ROOT"
            [ ! -e "$DRY_ROOT/home/pi/printer_data/config/ace.cfg" ] || fail 'dry-run wrote config'
            [ ! -e "$DRY_ROOT/home/pi/printer_data/config/ace_machine.cfg" ] || fail 'dry-run wrote machine config'
            printf '%s\n' 'PASS: dry-run; SKIP: Linux symlink transaction on Windows Git Bash.'
            exit 0
        fi
        ;;
esac

# Source-overlay compatibility is validated against each supported Fluidd
# source profile before any target is modified.
for version in 1.34.4 1.36.0 1.37.2; do
    VERSION_REPO=$TEMP/version-$version-repo
    VERSION_ROOT=$TEMP/version-$version-root
    make_fixture "$VERSION_REPO" "$VERSION_ROOT" "$version"
    run_installer "$VERSION_REPO" "$VERSION_ROOT" --dry-run --non-interactive \
        --fluidd-mode source --device-count 1 \
        --device 'ace1|/dev/serial/by-id/version-check'
    [ ! -e "$VERSION_ROOT/home/pi/printer_data/config/ace.cfg" ] ||
        fail "Fluidd $version dry-run wrote configuration"
done

# Compatibility-only mode must remain read-only.
CHECK_REPO=$TEMP/check-repo
CHECK_ROOT=$TEMP/check-root
make_fixture "$CHECK_REPO" "$CHECK_ROOT" 1.37.2
run_installer "$CHECK_REPO" "$CHECK_ROOT" --check-compatibility --fluidd-mode auto
[ ! -e "$CHECK_ROOT/home/pi/klipper/klippy/extras/ace" ] || fail 'compatibility check created a Klipper link'
[ ! -e "$CHECK_ROOT/home/pi/printer_data/config/ace.cfg" ] || fail 'compatibility check wrote configuration'
! grep -Fq 'ACE Driver V3 managed' "$CHECK_ROOT/home/pi/fluidd-src/src/views/Dashboard.vue" ||
    fail 'compatibility check patched Fluidd source'

# Unsupported Fluidd source falls back in auto mode, while source mode fails
# closed before creating any links or configuration.
AUTO_REPO=$TEMP/auto-fallback-repo
AUTO_ROOT=$TEMP/auto-fallback-root
make_fixture "$AUTO_REPO" "$AUTO_ROOT" 1.32.0
run_installer "$AUTO_REPO" "$AUTO_ROOT" --non-interactive --fluidd-mode auto \
    --device-count 1 --device 'ace1|/dev/serial/by-id/auto-fallback'
[ -L "$AUTO_ROOT/home/pi/fluidd/ace-v3/index.html" ] || fail 'auto fallback omitted standalone dashboard'
[ ! -L "$AUTO_ROOT/home/pi/fluidd-src/src/components/widgets/ace-v3/AceV3Card.vue" ] || fail 'auto fallback installed Fluidd overlay files'
! grep -Fq 'ACE Driver V3 managed' "$AUTO_ROOT/home/pi/fluidd-src/src/views/Dashboard.vue" ||
    fail 'auto fallback patched unsupported Fluidd source'

SOURCE_REPO=$TEMP/source-fail-repo
SOURCE_ROOT=$TEMP/source-fail-root
make_fixture "$SOURCE_REPO" "$SOURCE_ROOT" 1.32.0
if run_installer "$SOURCE_REPO" "$SOURCE_ROOT" --non-interactive --fluidd-mode source \
    --device-count 1 --device 'ace1|/dev/serial/by-id/source-fail'; then
    fail 'unsupported Fluidd unexpectedly passed forced source mode'
fi
[ ! -e "$SOURCE_ROOT/home/pi/klipper/klippy/extras/ace" ] || fail 'failed source mode created a Klipper link'
[ ! -e "$SOURCE_ROOT/home/pi/printer_data/config/ace.cfg" ] || fail 'failed source mode wrote configuration'

# Explicit legacy/custom config layouts are isolated from printer_data/config.
LEGACY_REPO=$TEMP/legacy-config-repo
LEGACY_ROOT=$TEMP/legacy-config-root
make_fixture "$LEGACY_REPO" "$LEGACY_ROOT" 1.37.2
mkdir -p "$LEGACY_ROOT/home/pi/klipper_config"
cp "$LEGACY_ROOT/home/pi/printer_data/config/printer.cfg" "$LEGACY_ROOT/home/pi/klipper_config/printer.cfg"
cp "$LEGACY_ROOT/home/pi/printer_data/config/moonraker.conf" "$LEGACY_ROOT/home/pi/klipper_config/moonraker.conf"
run_installer "$LEGACY_REPO" "$LEGACY_ROOT" --non-interactive \
    --config-dir /home/pi/klipper_config --device-count 1 \
    --device 'ace1|/dev/serial/by-id/legacy-layout'
[ -f "$LEGACY_ROOT/home/pi/klipper_config/ace.cfg" ] || fail 'custom config directory was not used'
[ ! -e "$LEGACY_ROOT/home/pi/printer_data/config/ace.cfg" ] || fail 'custom config install wrote the default config directory'

# The last split-layout release is migrated once. Hardware safety switches are
# retained, the active legacy file is retired, and uninstall keeps its archive.
MIGRATE_REPO=$TEMP/migrate-repo
MIGRATE_ROOT=$TEMP/migrate-root
make_fixture "$MIGRATE_REPO" "$MIGRATE_ROOT"
awk '
    /# >>> ACE DRIVER V3 HARDWARE TOPOLOGY BEGIN >>>/ { active=1; next }
    /# <<< ACE DRIVER V3 HARDWARE TOPOLOGY END <<</ { active=0; next }
    active { print }
' "$MIGRATE_REPO/config/ace.cfg" \
    > "$MIGRATE_ROOT/home/pi/printer_data/config/ace_hardware.cfg"
awk '
    /# >>> ACE DRIVER V3 HARDWARE TOPOLOGY BEGIN >>>/ {
        print "[include ace_hardware.cfg]"
        skip=1
        next
    }
    /# <<< ACE DRIVER V3 HARDWARE TOPOLOGY END <<</ { skip=0; next }
    !skip { print }
' "$MIGRATE_REPO/config/ace.cfg" \
    > "$MIGRATE_ROOT/home/pi/printer_data/config/ace.cfg"
sed -i '0,/^rfid_enabled: True/s//rfid_enabled: False/' \
    "$MIGRATE_ROOT/home/pi/printer_data/config/ace_hardware.cfg"
sed -i '0,/^physical_actions_enabled: False/s//physical_actions_enabled: True/' \
    "$MIGRATE_ROOT/home/pi/printer_data/config/ace_hardware.cfg"
run_installer "$MIGRATE_REPO" "$MIGRATE_ROOT" --non-interactive \
    --device-count 1 --device 'ace1|/dev/serial/by-id/REPLACE_WITH_STABLE_ACE1_PATH'
MIGRATED_SHARED=$MIGRATE_ROOT/home/pi/printer_data/config/ace.cfg
MIGRATED_ARCHIVE=$MIGRATE_ROOT/home/pi/printer_data/config/.ace-driver-v3/legacy/ace_hardware.cfg
[ ! -e "$MIGRATE_ROOT/home/pi/printer_data/config/ace_hardware.cfg" ] || fail 'legacy hardware config remained active after migration'
[ -f "$MIGRATED_ARCHIVE" ] || fail 'legacy hardware config was not archived'
assert_file_contains "$MIGRATED_ARCHIVE" 'rfid_enabled: False'
assert_file_contains "$MIGRATED_SHARED" 'rfid_enabled: False'
assert_file_contains "$MIGRATED_SHARED" 'physical_actions_enabled: True'
! grep -Fq '[include ace_hardware.cfg]' "$MIGRATED_SHARED" || fail 'legacy hardware include remained after migration'
"${PYTHON_BIN:-python3}" "$MIGRATE_REPO/scripts/hardware_config.py" \
    validate-embedded "$MIGRATED_SHARED"
run_installer "$MIGRATE_REPO" "$MIGRATE_ROOT" --uninstall
[ -f "$MIGRATED_ARCHIVE" ] || fail 'uninstall removed the migrated hardware archive'

# A restored split layout may legitimately need migration again. Existing
# archives are historical records and must never be overwritten.
awk '
    /# >>> ACE DRIVER V3 HARDWARE TOPOLOGY BEGIN >>>/ { active=1; next }
    /# <<< ACE DRIVER V3 HARDWARE TOPOLOGY END <<</ { active=0; next }
    active { print }
' "$MIGRATED_SHARED" \
    > "$MIGRATE_ROOT/home/pi/printer_data/config/ace_hardware.cfg"
awk '
    /# >>> ACE DRIVER V3 HARDWARE TOPOLOGY BEGIN >>>/ {
        print "[include ace_hardware.cfg]"
        skip=1
        next
    }
    /# <<< ACE DRIVER V3 HARDWARE TOPOLOGY END <<</ { skip=0; next }
    !skip { print }
' "$MIGRATED_SHARED" > "$MIGRATED_SHARED.new"
mv -- "$MIGRATED_SHARED.new" "$MIGRATED_SHARED"
run_installer "$MIGRATE_REPO" "$MIGRATE_ROOT" --non-interactive \
    --device-count 1 --device 'ace1|/dev/serial/by-id/REPLACE_WITH_STABLE_ACE1_PATH'
[ "$(find "$MIGRATE_ROOT/home/pi/printer_data/config/.ace-driver-v3/legacy" \
    -maxdepth 1 -type f -name 'ace_hardware*.cfg' | wc -l)" -eq 2 ] ||
    fail 'second migration overwrote or omitted a hardware archive'
[ ! -e "$MIGRATE_ROOT/home/pi/printer_data/config/ace_hardware.cfg" ] ||
    fail 'second migration left ace_hardware.cfg active'
run_installer "$MIGRATE_REPO" "$MIGRATE_ROOT" --uninstall

REPO=$TEMP/repo
ROOT=$TEMP/root
make_fixture "$REPO" "$ROOT"

INSTALL_OUTPUT=$(run_installer "$REPO" "$ROOT" --non-interactive --device-count 2 \
    --device 'ace1|/dev/serial/by-id/ace-one' \
    --device 'ace2|/dev/serial/by-id/ace-two|bus0|uid-ace-two' 2>&1) || {
        printf '%s\n' "$INSTALL_OUTPUT" >&2
        fail 'new installation failed'
    }
printf '%s\n' "$INSTALL_OUTPUT" | grep -Fq 'persistent pre-install snapshot:' ||
    fail 'installation did not report the persistent snapshot path'
printf '%s\n' "$INSTALL_OUTPUT" | grep -Fq 'restore command (stop Klipper and Moonraker first):' ||
    fail 'installation did not report the restore command'
printf '%s\n' "$INSTALL_OUTPUT" | grep -Fq 'REQUIRED: the Fluidd source patch is not live until dist is built and deployed' ||
    fail 'installation did not explain that patched Fluidd source must be built and deployed'
printf '%s\n' "$INSTALL_OUTPUT" | grep -Fq 'Fluidd toolchain: pnpm@9.15.4' ||
    fail 'installation did not report the Fluidd versioned toolchain'
printf '%s\n' "$INSTALL_OUTPUT" | grep -Fq 'Example deploy command: rsync -a --delete' ||
    fail 'installation did not report a dist deployment example'

SNAPSHOT=$(find "$ROOT/home/pi/printer_data/ace-driver-v3-snapshots" \
    -mindepth 1 -maxdepth 1 -type d | head -n 1)
[ -n "$SNAPSHOT" ] || fail 'persistent pre-install snapshot directory is missing'
[ -f "$SNAPSHOT/restore.py" ] || fail 'snapshot is missing its self-contained restore script'
[ -f "$SNAPSHOT/snapshot-manifest.json" ] || fail 'snapshot manifest is missing'
[ -f "$SNAPSHOT/SHA256SUMS" ] || fail 'snapshot checksums are missing'
"${PYTHON_BIN:-python3}" "$SNAPSHOT/restore.py" verify "$SNAPSHOT" >/dev/null
assert_file_contains "$SNAPSHOT/snapshot-manifest.json" "/home/pi/printer_data/config/printer.cfg"
assert_file_contains "$SNAPSHOT/snapshot-manifest.json" "/home/pi/fluidd-src/src/views/Dashboard.vue"
assert_file_contains "$SNAPSHOT/snapshot-manifest.json" "/home/pi/klipper/klippy/extras/ace"

PACKAGE_LINK=$ROOT/home/pi/klipper/klippy/extras/ace
[ -L "$PACKAGE_LINK" ] || fail 'whole ace_driver package was not linked'
[ "$(readlink "$PACKAGE_LINK")" = "$REPO/ace_driver" ] || fail 'package link target is wrong'
assert_wrapper_links "$REPO" "$ROOT"
[ -L "$ROOT/home/pi/moonraker/moonraker/components/ace_status.py" ] || fail 'Moonraker link missing'
[ -L "$ROOT/home/pi/fluidd/ace-v3/index.html" ] || fail 'dashboard link missing'
[ -L "$ROOT/home/pi/fluidd/shared/ace-core.js" ] || fail 'shared frontend link missing'
[ -L "$ROOT/home/pi/fluidd-src/src/components/widgets/ace-v3/AceV3Card.vue" ] || fail 'Fluidd overlay link missing'
[ -L "$ROOT/home/pi/fluidd-src/src/views/AcePro.vue" ] || fail 'Fluidd ACE Pro page link missing'
assert_file_contains "$ROOT/home/pi/printer_data/config/ace.cfg" 'toolchange_mode: manual'
assert_file_contains "$ROOT/home/pi/printer_data/config/ace.cfg" 'toolhead_sensor_bypass_load_length: 25'
assert_file_contains "$ROOT/home/pi/printer_data/config/ace.cfg" 'toolhead_sensor_bypass_calibrated: False'
assert_file_contains "$ROOT/home/pi/printer_data/config/ace.cfg" '# >>> ACE DRIVER V3 HARDWARE TOPOLOGY BEGIN >>>'
assert_file_contains "$ROOT/home/pi/printer_data/config/ace.cfg" 'device_count: 2'
assert_file_contains "$ROOT/home/pi/printer_data/config/ace.cfg" 'physical_actions_enabled: False'
! grep -Fq '[include ace_hardware.cfg]' "$ROOT/home/pi/printer_data/config/ace.cfg" || fail 'new install retained legacy hardware include'
[ ! -e "$ROOT/home/pi/printer_data/config/ace_hardware.cfg" ] || fail 'new install created retired ace_hardware.cfg'
"${PYTHON_BIN:-python3}" "$REPO/scripts/hardware_config.py" validate-embedded \
    "$ROOT/home/pi/printer_data/config/ace.cfg"
assert_file_contains "$ROOT/home/pi/printer_data/config/ace.cfg" '# [gcode_macro _ace_cut_filament]'
assert_file_contains "$ROOT/home/pi/printer_data/config/ace.cfg" '[gcode_macro _ace_load_filament_to_toolhead]'
assert_file_contains "$ROOT/home/pi/printer_data/config/ace.cfg" '打印中允许启用辅助送料，但必须由用户显式确认'
assert_file_contains "$ROOT/home/pi/printer_data/config/ace.cfg" '固定注册 T0..T15 和 TR'
if [ -e "$ROOT/home/pi/printer_data/config/ace_machine.cfg" ]; then
    fail 'new install still created retired ace_machine.cfg'
fi
assert_file_contains "$ROOT/home/pi/printer_data/config/printer.cfg" '[include ace.cfg]'
[ "$(grep -nF 'ACE Driver V3 managed include' "$ROOT/home/pi/printer_data/config/printer.cfg" | head -n 1 | cut -d: -f1)" -lt \
  "$(grep -nF 'SAVE_CONFIG' "$ROOT/home/pi/printer_data/config/printer.cfg" | head -n 1 | cut -d: -f1)" ] ||
    fail 'printer include was written after SAVE_CONFIG'
assert_file_contains "$ROOT/home/pi/printer_data/config/moonraker.conf" '[ace_status]'
assert_file_contains "$ROOT/home/pi/fluidd-src/src/views/Dashboard.vue" 'ACE Driver V3 managed import'
assert_file_contains "$ROOT/home/pi/fluidd-src/src/store/layout/state.ts" 'ACE Driver V3 managed card'
assert_file_contains "$ROOT/home/pi/fluidd-src/src/router/index.ts" 'ACE Driver V3 managed route'
assert_file_contains "$ROOT/home/pi/fluidd-src/src/components/layout/AppNavDrawer.vue" 'ACE Driver V3 managed navigation'

# Reconfiguration is idempotent, rewrites embedded hardware topology, and upgrades the
# V3-owned config contract without replacing user calibration.
printf '%s\n' '# user-calibrated-value' >> "$ROOT/home/pi/printer_data/config/ace.cfg"
sed -i '0,/^rfid_enabled: True/s//rfid_enabled: False/' "$ROOT/home/pi/printer_data/config/ace.cfg"
sed -i '0,/^physical_actions_enabled: False/s//physical_actions_enabled: True/' "$ROOT/home/pi/printer_data/config/ace.cfg"
sed -i 's/^toolchange_mode: manual/toolchange_mode: automatic/' "$ROOT/home/pi/printer_data/config/ace.cfg"
sed -i 's/^toolhead_sensor_bypass_load_length: 25/toolhead_sensor_bypass_load_length: 37/' "$ROOT/home/pi/printer_data/config/ace.cfg"
sed -i 's/^toolhead_sensor_bypass_calibrated: False/toolhead_sensor_bypass_calibrated: True/' "$ROOT/home/pi/printer_data/config/ace.cfg"
sed -i '/^toolhead_sensor_pin:/d' "$ROOT/home/pi/printer_data/config/ace.cfg"
sed -i 's/^load_to_toolhead_macro:.*/load_to_toolhead_macro:/' "$ROOT/home/pi/printer_data/config/ace.cfg"
printf '%s\n' '# encoder-wrapper-update' >> "$REPO/klipper_extras/ace_encoder.py"
rm -- "$ROOT/home/pi/klipper/klippy/extras/ace_encoder.py"
cat > "$ROOT/home/pi/printer_data/config/ace_machine.cfg" <<'EOF'
# user-machine-calibration
[gcode_macro _ACE_MACHINE_PRE_TOOLCHANGE]
variable_park_x: 289
gcode:
    G4 P0
EOF
run_installer "$REPO" "$ROOT" --non-interactive --device-count 1 \
    --device 'ace1|/dev/serial/by-id/ace-one'
assert_wrapper_links "$REPO" "$ROOT"
assert_file_contains "$ROOT/home/pi/klipper/klippy/extras/ace_encoder.py" '# encoder-wrapper-update'
[ "$(grep -Fc "$ROOT/home/pi/klipper/klippy/extras/ace_encoder.py|" "$ROOT/home/pi/printer_data/config/.ace-driver-v3/links.manifest")" -eq 1 ] ||
    fail 'ace_encoder wrapper manifest entry was duplicated during update'
assert_file_contains "$ROOT/home/pi/printer_data/config/ace.cfg" 'device_count: 1'
assert_file_contains "$ROOT/home/pi/printer_data/config/ace.cfg" 'rfid_enabled: False'
assert_file_contains "$ROOT/home/pi/printer_data/config/ace.cfg" 'physical_actions_enabled: True'
[ "$(grep -Fc 'ACE DRIVER V3 HARDWARE TOPOLOGY BEGIN' "$ROOT/home/pi/printer_data/config/ace.cfg")" -eq 1 ] || fail 'embedded hardware block was duplicated'
[ ! -e "$ROOT/home/pi/printer_data/config/ace_hardware.cfg" ] || fail 'reconfiguration created retired ace_hardware.cfg'
assert_file_contains "$ROOT/home/pi/printer_data/config/ace.cfg" '# user-calibrated-value'
assert_file_contains "$ROOT/home/pi/printer_data/config/ace.cfg" 'toolchange_mode: automatic'
assert_file_contains "$ROOT/home/pi/printer_data/config/ace.cfg" 'toolhead_sensor_bypass_load_length: 37'
assert_file_contains "$ROOT/home/pi/printer_data/config/ace.cfg" 'toolhead_sensor_bypass_calibrated: True'
assert_file_contains "$ROOT/home/pi/printer_data/config/ace.cfg" 'toolhead_sensor_pin:'
assert_file_contains "$ROOT/home/pi/printer_data/config/ace.cfg" 'load_to_toolhead_macro: _ace_load_filament_to_toolhead'
assert_file_contains "$ROOT/home/pi/printer_data/config/ace.cfg" 'variable_park_x: 289'
assert_file_contains "$ROOT/home/pi/printer_data/config/ace.cfg" 'ACE_PATH_LOAD_TO_TOOLHEAD'
assert_file_contains "$ROOT/home/pi/printer_data/config/ace.cfg" 'ACE_PATH_UNLOAD_STEP'
assert_file_contains "$ROOT/home/pi/printer_data/config/ace.cfg" '[gcode_macro _ace_prepare_toolchange]'
! grep -Fq '[gcode_macro _ACE_MACHINE_PRE_TOOLCHANGE]' "$ROOT/home/pi/printer_data/config/ace.cfg" || fail 'legacy macro remained active after migration'
assert_file_contains "$ROOT/home/pi/printer_data/config/ace_machine.cfg.legacy" '# user-machine-calibration'
[ ! -e "$ROOT/home/pi/printer_data/config/ace_machine.cfg" ] || fail 'legacy machine config was not archived'
! grep -Fq '[include ace_machine.cfg]' "$ROOT/home/pi/printer_data/config/ace.cfg" || fail 'retired machine include remains'
[ "$(grep -Fc 'ACE Driver V3 managed include' "$ROOT/home/pi/printer_data/config/printer.cfg")" -eq 2 ] || fail 'printer managed block duplicated'
[ "$(grep -Fc 'ACE Driver V3 managed route' "$ROOT/home/pi/fluidd-src/src/router/index.ts")" -eq 2 ] || fail 'Fluidd route patch duplicated'
[ "$(grep -Fc 'ACE Driver V3 managed navigation' "$ROOT/home/pi/fluidd-src/src/components/layout/AppNavDrawer.vue")" -eq 2 ] || fail 'Fluidd navigation patch duplicated'

# A Fluidd upgrade may remove one of the previously patched source files.
# Uninstall must still clean the remaining registrations and driver links.
rm -- "$ROOT/home/pi/fluidd-src/src/store/layout/state.ts"
run_installer "$REPO" "$ROOT" --uninstall
[ ! -e "$PACKAGE_LINK" ] || fail 'package link remains after uninstall'
assert_wrappers_absent "$ROOT"
[ ! -e "$ROOT/home/pi/fluidd/ace-v3/index.html" ] || fail 'dashboard link remains after uninstall'
[ ! -e "$ROOT/home/pi/fluidd-src/src/components/widgets/ace-v3/AceV3Card.vue" ] || fail 'overlay file remains after uninstall'
[ ! -L "$ROOT/home/pi/fluidd-src/src/views/AcePro.vue" ] || fail 'ACE Pro page link remains after uninstall'
assert_file_contains "$ROOT/home/pi/fluidd-src/src/views/AcePro.vue" 'original-v2-ace-page'
! grep -Fq 'ACE Driver V3 managed import' "$ROOT/home/pi/fluidd-src/src/views/Dashboard.vue" || fail 'Fluidd dashboard patch remains'
! grep -Fq 'ACE Driver V3 managed route' "$ROOT/home/pi/fluidd-src/src/router/index.ts" || fail 'Fluidd route patch remains'
! grep -Fq 'ACE Driver V3 managed navigation' "$ROOT/home/pi/fluidd-src/src/components/layout/AppNavDrawer.vue" || fail 'Fluidd navigation patch remains'
assert_file_contains "$ROOT/home/pi/fluidd-src/src/router/index.ts" "component: () => import('@/views/AcePro.vue')"
assert_file_contains "$ROOT/home/pi/fluidd-src/src/components/layout/AppNavDrawer.vue" 'v-if="supportsAcePro"'
[ -f "$ROOT/home/pi/printer_data/config/ace.cfg" ] || fail 'user config was removed'
[ -f "$ROOT/home/pi/printer_data/config/ace_machine.cfg.legacy" ] || fail 'legacy machine config archive was removed'
! grep -Fq 'ACE Driver V3 managed include' "$ROOT/home/pi/printer_data/config/printer.cfg" || fail 'printer managed block remains'

# Dry-run must not write a single target.
DRY_REPO=$TEMP/dry-repo
DRY_ROOT=$TEMP/dry-root
make_fixture "$DRY_REPO" "$DRY_ROOT"
run_installer "$DRY_REPO" "$DRY_ROOT" --dry-run --non-interactive --device-count 1 \
    --device 'ace1|/dev/serial/by-id/dry'
[ ! -e "$DRY_ROOT/home/pi/klipper/klippy/extras/ace" ] || fail 'dry-run created package link'
assert_wrappers_absent "$DRY_ROOT"
[ ! -e "$DRY_ROOT/home/pi/printer_data/config/ace.cfg" ] || fail 'dry-run wrote config'
[ ! -e "$DRY_ROOT/home/pi/printer_data/config/ace_machine.cfg" ] || fail 'dry-run wrote machine config'

# A conflict after the first link must roll back all earlier writes.
FAIL_REPO=$TEMP/fail-repo
FAIL_ROOT=$TEMP/fail-root
make_fixture "$FAIL_REPO" "$FAIL_ROOT"
printf '%s\n' 'unmanaged component' > "$FAIL_ROOT/home/pi/moonraker/moonraker/components/ace_status.py"
if run_installer "$FAIL_REPO" "$FAIL_ROOT" --non-interactive --device-count 1 \
    --device 'ace1|/dev/serial/by-id/fail'; then
    fail 'conflicting Moonraker component unexpectedly installed'
fi
[ ! -e "$FAIL_ROOT/home/pi/klipper/klippy/extras/ace" ] || fail 'failed transaction left package link'
assert_wrappers_absent "$FAIL_ROOT"
assert_file_contains "$FAIL_ROOT/home/pi/moonraker/moonraker/components/ace_status.py" 'unmanaged component'

# Embedded topology and an independent hardware file are ambiguous. Refuse the
# install before creating links or choosing one source's safety switches.
DOUBLE_REPO=$TEMP/double-source-repo
DOUBLE_ROOT=$TEMP/double-source-root
make_fixture "$DOUBLE_REPO" "$DOUBLE_ROOT"
cp -- "$DOUBLE_REPO/config/ace.cfg" \
    "$DOUBLE_ROOT/home/pi/printer_data/config/ace.cfg"
awk '
    /# >>> ACE DRIVER V3 HARDWARE TOPOLOGY BEGIN >>>/ { active=1; next }
    /# <<< ACE DRIVER V3 HARDWARE TOPOLOGY END <<</ { active=0; next }
    active { print }
' "$DOUBLE_REPO/config/ace.cfg" \
    > "$DOUBLE_ROOT/home/pi/printer_data/config/ace_hardware.cfg"
if run_installer "$DOUBLE_REPO" "$DOUBLE_ROOT" --non-interactive \
    --device-count 1 --device 'ace1|/dev/serial/by-id/double-source'; then
    fail 'ambiguous embedded and standalone hardware sources were accepted'
fi
[ ! -e "$DOUBLE_ROOT/home/pi/klipper/klippy/extras/ace" ] ||
    fail 'double-source rejection created a package link'
[ -f "$DOUBLE_ROOT/home/pi/printer_data/config/ace_hardware.cfg" ] ||
    fail 'double-source rejection modified the legacy hardware file'

# A failure after Fluidd patching must restore all four patched source files.
PATCH_FAIL_REPO=$TEMP/patch-fail-repo
PATCH_FAIL_ROOT=$TEMP/patch-fail-root
make_fixture "$PATCH_FAIL_REPO" "$PATCH_FAIL_ROOT"
printf '%s\n' '[ace_status]' >> "$PATCH_FAIL_ROOT/home/pi/printer_data/config/moonraker.conf"
if PATCH_FAIL_OUTPUT=$(run_installer "$PATCH_FAIL_REPO" "$PATCH_FAIL_ROOT" \
    --non-interactive --device-count 1 \
    --device 'ace1|/dev/serial/by-id/patch-fail' 2>&1); then
    fail 'late Moonraker config conflict unexpectedly installed'
fi
printf '%s\n' "$PATCH_FAIL_OUTPUT" | grep -Fq 'rolling back incomplete transaction' ||
    fail 'late failure did not report transaction rollback'
printf '%s\n' "$PATCH_FAIL_OUTPUT" | grep -Fq 'snapshot retained:' ||
    fail 'late failure did not report the retained snapshot'
PATCH_FAIL_SNAPSHOT=$(find \
    "$PATCH_FAIL_ROOT/home/pi/printer_data/ace-driver-v3-snapshots" \
    -mindepth 1 -maxdepth 1 -type d | head -n 1)
[ -n "$PATCH_FAIL_SNAPSHOT" ] || fail 'late failure removed the persistent snapshot'
"${PYTHON_BIN:-python3}" "$PATCH_FAIL_SNAPSHOT/restore.py" verify \
    "$PATCH_FAIL_SNAPSHOT" >/dev/null
[ ! -e "$PATCH_FAIL_ROOT/home/pi/klipper/klippy/extras/ace" ] || fail 'late failure left package link'
assert_wrappers_absent "$PATCH_FAIL_ROOT"
assert_file_contains "$PATCH_FAIL_ROOT/home/pi/fluidd-src/src/views/AcePro.vue" 'original-v2-ace-page'
! grep -Fq 'ACE Driver V3 managed import' "$PATCH_FAIL_ROOT/home/pi/fluidd-src/src/views/Dashboard.vue" || fail 'late failure left dashboard patch'
! grep -Fq 'ACE Driver V3 managed card' "$PATCH_FAIL_ROOT/home/pi/fluidd-src/src/store/layout/state.ts" || fail 'late failure left layout patch'
! grep -Fq 'ACE Driver V3 managed route' "$PATCH_FAIL_ROOT/home/pi/fluidd-src/src/router/index.ts" || fail 'late failure left route patch'
! grep -Fq 'ACE Driver V3 managed navigation' "$PATCH_FAIL_ROOT/home/pi/fluidd-src/src/components/layout/AppNavDrawer.vue" || fail 'late failure left navigation patch'

printf '%s\n' 'installer integration tests passed'
