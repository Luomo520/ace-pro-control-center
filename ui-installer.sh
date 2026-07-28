#!/usr/bin/env sh
set -eu

APP_ID="ace-pro-control-center"
REPOSITORY_URL="https://github.com/Luomo520/ace-pro-control-center"
TESTED_FLUIDD_VERSION="1.37.2"
TESTED_MOONRAKER_MIN_VERSION="0.9.3"
TESTED_MOONRAKER_MAX_VERSION="0.9.3"
ROOT_DIR=$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)
PACKAGE_VERSION=$(sed -n '1p' "$ROOT_DIR/VERSION" 2>/dev/null || printf 'unknown')

FLUIDD_ROOT=${FLUIDD_ROOT:-"$HOME/fluidd"}
KLIPPER_ROOT=${KLIPPER_ROOT:-"$HOME/klipper"}
KLIPPER_PYTHON=${KLIPPER_PYTHON:-"$HOME/klippy-env/bin/python"}
MOONRAKER_ROOT=${MOONRAKER_ROOT:-"$HOME/moonraker"}
PRINTER_CONFIG_DIR=${PRINTER_CONFIG_DIR:-"$HOME/printer_data/config"}
PRINTER_CFG=${PRINTER_CFG:-"$PRINTER_CONFIG_DIR/printer.cfg"}
MOONRAKER_CONF=${MOONRAKER_CONF:-"$PRINTER_CONFIG_DIR/moonraker.conf"}
ACE_CC_ROOT=${ACE_CC_ROOT:-"$HOME/ace-pro-control-center"}
STATE_DIR=${ACE_CC_STATE_DIR:-"$HOME/.local/share/ace-pro-control-center"}
OLD_ROOT="$STATE_DIR/old"
BASELINE_FILE="$STATE_DIR/first-install-old"
DRIVER_BASELINE_FILE="$STATE_DIR/first-install-old-driver"
CARD_BASELINE_FILE="$STATE_DIR/first-install-old-card"
MARKER="$STATE_DIR/installed"

PAYLOAD_DRIVER="$ROOT_DIR/extras/ace.py"
PAYLOAD_CONFIG="$ROOT_DIR/ace.cfg"
PAYLOAD_REQUIREMENTS="$ROOT_DIR/requirements.txt"
PAYLOAD_FLUIDD="$ROOT_DIR/fluidd-dist"
PAYLOAD_MOONRAKER="$ROOT_DIR/ace_status_integration/moonraker/ace_status.py"
PAYLOAD_WEB="$ROOT_DIR/ace_status_integration/web"

TARGET_DRIVER_ROOT="$ACE_CC_ROOT/extras/ace.py"
TARGET_DRIVER_LINK="$KLIPPER_ROOT/klippy/extras/ace.py"
TARGET_CONFIG_ROOT="$ACE_CC_ROOT/ace.cfg"
TARGET_CONFIG_LINK="$PRINTER_CONFIG_DIR/ace.cfg"
TARGET_COMPONENT="$MOONRAKER_ROOT/moonraker/components/ace_status.py"
TARGET_WEB="$ACE_CC_ROOT/ace_status_integration/web"

GENERATED_CONFIG=""
YES=0
LANG_CODE=""
TRANSACTION_ARCHIVE=""
TRANSACTION_ACTIVE=0
TRANSACTION_RECOVERING=0
TRANSACTION_RECOVERY_FAILED=0
ARCHIVE_ITEM_INDEX=0
RESTORE_ITEM_INDEX=0
REPLACE_ITEM_INDEX=0

detect_language() {
  requested=${ACE_CC_LANG:-${LC_ALL:-${LC_MESSAGES:-${LANG:-}}}}
  case "$requested" in
    zh*|ZH*) printf '%s\n' 'zh-CN' ;;
    *) printf '%s\n' 'en-US' ;;
  esac
}

LANG_CODE=$(detect_language)

t() {
  key=$1
  if [ "$LANG_CODE" = "zh-CN" ]; then
    case "$key" in
      app_name) printf '%s' 'ACE Pro 管理中心' ;;
      ok) printf '%s' '成功' ;;
      warning) printf '%s' '警告' ;;
      failed) printf '%s' '失败' ;;
      unknown) printf '%s' '未知' ;;
      not_installed) printf '%s' '未安装' ;;
      installed) printf '%s' '已安装' ;;
      menu_install_all) printf '%s' '安装 / 更新完整组件（驱动 + 卡片）' ;;
      menu_install_driver) printf '%s' '仅安装 / 更新驱动并修复 ace.cfg 可编辑状态' ;;
      menu_install_card) printf '%s' '仅安装 / 更新 Fluidd 卡片和 Moonraker 组件' ;;
      menu_force) printf '%s' '强制安装完整组件（仍执行校验和归档）' ;;
      menu_rollback) printf '%s' '回滚最近一次安装' ;;
      menu_uninstall) printf '%s' '卸载并恢复首次安装前状态' ;;
      menu_status) printf '%s' '检查当前状态' ;;
      menu_exit) printf '%s' '退出' ;;
      choose) printf '%s' '请选择' ;;
      confirm) printf '%s' '确认继续？目标文件会先进入归档' ;;
      press_enter) printf '%s' '按 Enter 返回菜单...' ;;
      cancelled) printf '%s' '用户取消，未修改文件' ;;
      payload_bad) printf '%s' '安装文件校验失败，请重新通过 Git 下载完整仓库' ;;
      archive_failed) printf '%s' '安装前归档失败，未开始写入' ;;
      install_failed) printf '%s' '安装失败，已尝试恢复安装前状态' ;;
      install_ok_all) printf '%s' '驱动、Moonraker、Fluidd 卡片和辅助页面安装完成' ;;
      install_ok_driver) printf '%s' '驱动和配置安装完成，Fluidd 保持不变' ;;
      install_ok_card) printf '%s' 'Fluidd 卡片和 Moonraker 组件安装完成，驱动保持不变' ;;
      restart_notice) printf '%s' '安装器不会自动重启服务；请在确认未打印后重启 Klipper 和 Moonraker' ;;
      rollback_hint) printf '%s' '如有问题，可使用 --rollback-latest 恢复安装前版本' ;;
      config_required) printf '%s' '上下传感器引脚未填写；必须编辑 ace.cfg 后才能重启 Klipper' ;;
      config_editable) printf '%s' 'ace.cfg 已安装为配置目录内的普通可写文件，Fluidd 可直接编辑' ;;
      config_mode_editable) printf '%s' '普通可写文件' ;;
      config_mode_locked) printf '%s' '旧版外部软链接（Fluidd 会显示锁；重新安装驱动可修复）' ;;
      config_mode_missing) printf '%s' '不存在' ;;
      config_preserved) printf '%s' '检测到现有 ace.cfg：保留模式不会询问或改写传感器配置；新版模板仅写入 ace.cfg.example' ;;
      fiveway_question) printf '%s' '是否安装五通传感器？1=已安装 2=未安装 3=稍后配置' ;;
      upper_pin) printf '%s' '上方传感器 MCU 引脚（可留空稍后填写）' ;;
      lower_pin) printf '%s' '下方传感器 MCU 引脚（可留空稍后填写）' ;;
      parking_pin) printf '%s' '五通传感器 MCU 引脚（可留空）' ;;
      parking_position) printf '%s' '传感器位置：1=五通之后 2=五通之前' ;;
      version_risk) printf '%s' '前端或 Moonraker 版本未在本包完整验证范围内' ;;
      risk_choice) printf '%s' '1=仅安装驱动 2=继续完整安装 3=取消' ;;
      force_notice) printf '%s' '强制模式仅跳过兼容性阻断，不跳过校验、归档或失败恢复' ;;
      risk_noninteractive) printf '%s' '检测到 Fluidd/Moonraker 兼容性风险；普通 --yes 安装已拒绝，请检查版本或明确使用 --install-force' ;;
      root_refused) printf '%s' '拒绝以 root 运行安装、回滚或卸载；请使用拥有 Klipper 文件的普通用户执行' ;;
      source_overlap) printf '%s' '源码目录与运行目录相同或互相包含；为避免移动安装器自身，操作已拒绝' ;;
      path_resolution_failed) printf '%s' '无法解析源码目录或运行目录的绝对路径；操作已拒绝' ;;
      invalid_config_mode) printf '%s' 'ACE_CC_CONFIG_MODE 仅允许 preserve 或 replace；操作已拒绝' ;;
      no_baseline) printf '%s' '没有找到首次安装前归档' ;;
      rollback_ok) printf '%s' '已恢复最近一次安装前状态' ;;
      uninstall_ok) printf '%s' '已恢复首次安装前状态' ;;
      *) printf '%s' "$key" ;;
    esac
  else
    case "$key" in
      app_name) printf '%s' 'Ace Pro Control Center' ;;
      ok) printf '%s' 'OK' ;;
      warning) printf '%s' 'WARN' ;;
      failed) printf '%s' 'FAIL' ;;
      unknown) printf '%s' 'unknown' ;;
      not_installed) printf '%s' 'not installed' ;;
      installed) printf '%s' 'installed' ;;
      menu_install_all) printf '%s' 'Install / update complete suite (driver + card)' ;;
      menu_install_driver) printf '%s' 'Install / update driver and repair ace.cfg editability' ;;
      menu_install_card) printf '%s' 'Install / update Fluidd card and Moonraker component only' ;;
      menu_force) printf '%s' 'Force complete installation (verification and archive remain enabled)' ;;
      menu_rollback) printf '%s' 'Roll back the latest installation' ;;
      menu_uninstall) printf '%s' 'Uninstall and restore the pre-installation baseline' ;;
      menu_status) printf '%s' 'Check current status' ;;
      menu_exit) printf '%s' 'Exit' ;;
      choose) printf '%s' 'Select' ;;
      confirm) printf '%s' 'Continue? Target files will be archived first' ;;
      press_enter) printf '%s' 'Press Enter to return...' ;;
      cancelled) printf '%s' 'Cancelled; no files were changed' ;;
      payload_bad) printf '%s' 'Payload verification failed; download the complete repository with Git' ;;
      archive_failed) printf '%s' 'Pre-installation archive failed; no new files were written' ;;
      install_failed) printf '%s' 'Installation failed; the installer attempted to restore the previous state' ;;
      install_ok_all) printf '%s' 'Driver, Moonraker component, Fluidd card and fallback page installed' ;;
      install_ok_driver) printf '%s' 'Driver and configuration installed; Fluidd was not changed' ;;
      install_ok_card) printf '%s' 'Fluidd card and Moonraker component installed; driver was not changed' ;;
      restart_notice) printf '%s' 'Services are not restarted automatically; restart Klipper and Moonraker only while idle' ;;
      rollback_hint) printf '%s' 'Use --rollback-latest to restore the pre-installation version if needed' ;;
      config_required) printf '%s' 'Upper/lower sensor pins are blank; edit ace.cfg before restarting Klipper' ;;
      config_editable) printf '%s' 'ace.cfg is a regular writable file inside the config directory and can be edited in Fluidd' ;;
      config_mode_editable) printf '%s' 'regular writable file' ;;
      config_mode_locked) printf '%s' 'legacy external symlink (locked in Fluidd; reinstall the driver to repair)' ;;
      config_mode_missing) printf '%s' 'missing' ;;
      config_preserved) printf '%s' 'Existing ace.cfg detected: preserve mode skips sensor questions and does not rewrite runtime sensor settings; the new template is written only to ace.cfg.example' ;;
      fiveway_question) printf '%s' 'Five-way sensor: 1=installed 2=not installed 3=configure later' ;;
      upper_pin) printf '%s' 'Upper sensor MCU pin (blank to configure later)' ;;
      lower_pin) printf '%s' 'Lower sensor MCU pin (blank to configure later)' ;;
      parking_pin) printf '%s' 'Five-way sensor MCU pin (blank to configure later)' ;;
      parking_position) printf '%s' 'Sensor position: 1=after five-way 2=before five-way' ;;
      version_risk) printf '%s' 'Fluidd or Moonraker is outside the fully tested package range' ;;
      risk_choice) printf '%s' '1=driver only 2=continue complete installation 3=cancel' ;;
      force_notice) printf '%s' 'Force mode bypasses compatibility blocking only, not verification, archive, or recovery' ;;
      risk_noninteractive) printf '%s' 'Fluidd/Moonraker compatibility risk detected; normal --yes installation is fail-closed. Inspect versions or explicitly use --install-force' ;;
      root_refused) printf '%s' 'Refusing to install, roll back, or uninstall as root; run as the regular user that owns the Klipper files' ;;
      source_overlap) printf '%s' 'The source directory and runtime directory are identical or contain one another; refusing to move the installer payload' ;;
      path_resolution_failed) printf '%s' 'Unable to resolve the source or runtime directory to an absolute path; refusing the operation' ;;
      invalid_config_mode) printf '%s' 'ACE_CC_CONFIG_MODE must be preserve or replace; refusing the operation' ;;
      no_baseline) printf '%s' 'No pre-installation baseline archive was found' ;;
      rollback_ok) printf '%s' 'Restored the state before the latest installation' ;;
      uninstall_ok) printf '%s' 'Restored the state before the first installation' ;;
      *) printf '%s' "$key" ;;
    esac
  fi
}

ok() { printf '[ %s ] %s\n' "$(t ok)" "$1"; }
warn() { printf '[ %s ] %s\n' "$(t warning)" "$1" >&2; }
bad() { printf '[ %s ] %s\n' "$(t failed)" "$1" >&2; }
line() { printf '%s\n' '+------------------------------------------------------------------------+'; }
path_exists() { [ -e "$1" ] || [ -L "$1" ]; }

require_non_root() {
  uid=$(id -u 2>/dev/null) || { bad 'Unable to determine the current user id'; return 1; }
  [ "$uid" != "0" ] || { bad "$(t root_refused)"; return 1; }
}

canonical_path() {
  candidate=$1
  if command -v realpath >/dev/null 2>&1; then
    realpath -m -- "$candidate"
    return
  fi
  if [ -d "$candidate" ]; then
    (CDPATH= cd -- "$candidate" 2>/dev/null && pwd -P)
    return
  fi
  parent=$(dirname -- "$candidate")
  name=$(basename -- "$candidate")
  resolved_parent=$(CDPATH= cd -- "$parent" 2>/dev/null && pwd -P) || return 1
  printf '%s/%s\n' "${resolved_parent%/}" "$name"
}

paths_overlap() {
  left=$1; right=$2
  [ "$left" = "$right" ] && return 0
  case "$left" in "$right"/*) return 0 ;; esac
  case "$right" in "$left"/*) return 0 ;; esac
  return 1
}

require_safe_layout() {
  source_root=$(canonical_path "$ROOT_DIR") || {
    bad "$(t path_resolution_failed): source=$ROOT_DIR, ACE_CC_ROOT=$ACE_CC_ROOT"
    return 1
  }
  runtime_root=$(canonical_path "$ACE_CC_ROOT") || {
    bad "$(t path_resolution_failed): source=$source_root, ACE_CC_ROOT=$ACE_CC_ROOT"
    return 1
  }
  if paths_overlap "$source_root" "$runtime_root"; then
    bad "$(t source_overlap): source=$source_root, ACE_CC_ROOT=$runtime_root"
    return 1
  fi
}

require_valid_config_mode() {
  case "$1" in
    preserve|replace) return 0 ;;
    *) bad "$(t invalid_config_mode): $1"; return 1 ;;
  esac
}

cleanup() {
  status=$?
  trap - EXIT HUP INT TERM
  if [ "$TRANSACTION_ACTIVE" = "1" ] && [ "$TRANSACTION_RECOVERING" = "0" ] && [ "$TRANSACTION_RECOVERY_FAILED" = "0" ]; then
    recover_transaction "exit-$status" || status=1
  fi
  [ -z "$GENERATED_CONFIG" ] || rm -f "$GENERATED_CONFIG"
  exit "$status"
}
trap cleanup EXIT
trap 'exit 129' HUP
trap 'exit 130' INT
trap 'exit 143' TERM

first_line() {
  if [ -s "$1" ]; then
    IFS= read -r value < "$1" || true
    printf '%s\n' "${value:-$(t unknown)}"
  else
    t unknown
    printf '\n'
  fi
}

detect_fluidd_version() {
  if [ -s "$FLUIDD_ROOT/.version" ]; then
    first_line "$FLUIDD_ROOT/.version"
  elif [ -s "$FLUIDD_ROOT/release_info.json" ]; then
    sed -n 's/.*"version"[[:space:]]*:[[:space:]]*"\([^"]*\)".*/\1/p' "$FLUIDD_ROOT/release_info.json" | head -n 1
  else
    t unknown; printf '\n'
  fi
}

detect_moonraker_version() {
  if [ -s "$MOONRAKER_ROOT/.version" ]; then
    first_line "$MOONRAKER_ROOT/.version"
  elif command -v git >/dev/null 2>&1 && [ -d "$MOONRAKER_ROOT/.git" ]; then
    git -C "$MOONRAKER_ROOT" describe --tags --always 2>/dev/null || true
  elif command -v curl >/dev/null 2>&1; then
    curl -fsS --max-time 3 http://127.0.0.1:7125/server/info 2>/dev/null |
      sed -n 's/.*"moonraker_version"[[:space:]]*:[[:space:]]*"\([^"]*\)".*/\1/p' | head -n 1
  else
    t unknown; printf '\n'
  fi
}

normalize_version() {
  printf '%s' "$1" | sed -n 's/^[^0-9]*\([0-9][0-9]*\.[0-9][0-9]*\.[0-9][0-9]*\).*$/\1/p'
}

compare_versions() {
  awk -F. -v left="$1" -v right="$2" 'BEGIN {
    split(left, a, "."); split(right, b, ".");
    for (i = 1; i <= 3; i++) {
      if ((a[i] + 0) < (b[i] + 0)) { print -1; exit }
      if ((a[i] + 0) > (b[i] + 0)) { print 1; exit }
    }
    print 0
  }'
}

detect_driver_version() {
  driver=$TARGET_DRIVER_LINK
  path_exists "$driver" || driver=$TARGET_DRIVER_ROOT
  if path_exists "$driver"; then
    value=$(sed -n 's/^ACE_PRO_CONTROL_CENTER_DRIVER_VERSION = ["'"']\([^"'"']*\)["'"'].*/\1/p' "$driver" 2>/dev/null | head -n 1)
    [ -n "$value" ] && printf '%s\n' "$value" || t unknown
  else
    t not_installed
  fi
}

latest_old() {
  [ -d "$OLD_ROOT" ] || return 0
  find "$OLD_ROOT" -mindepth 1 -maxdepth 1 -type d -name '20*' 2>/dev/null |
    sort | tail -n 1 | sed 's#^.*/##'
}

header() {
  command -v clear >/dev/null 2>&1 && clear || true
  line
  printf '| %-70s |\n' "$(t app_name)"
  line
  printf '  Fluidd     : %s\n' "$(detect_fluidd_version)"
  printf '  Moonraker  : %s\n' "$(detect_moonraker_version)"
  printf '  Driver     : %s\n' "$(detect_driver_version)"
  printf '  Package    : %s\n' "$PACKAGE_VERSION"
  printf '  Language   : %s\n' "$LANG_CODE"
  printf '  State      : %s\n' "$([ -f "$MARKER" ] && t installed || t not_installed)"
  printf '  Last archive: %s\n' "$(latest_old || t unknown)"
  line
}

confirm() {
  [ "$YES" = "1" ] && return 0
  printf '%s [y/N]: ' "$1" >&2
  IFS= read -r answer || return 1
  case "$answer" in y|Y|yes|YES) return 0 ;; *) return 1 ;; esac
}

choose_language() {
  printf '%s\n' '1. 简体中文' '2. English'
  printf '[1/2]: '
  IFS= read -r answer || answer=''
  case "$answer" in 2) LANG_CODE='en-US' ;; 1) LANG_CODE='zh-CN' ;; esac
}

valid_pin() {
  [ -z "$1" ] || printf '%s' "$1" | grep -Eq '^[A-Za-z0-9_:.!^~/-]+$'
}

collect_config_answers() {
  [ "$YES" = "0" ] || return 0
  printf '%s: ' "$(t upper_pin)"; IFS= read -r ACE_CC_UPPER_SENSOR_PIN || true
  printf '%s: ' "$(t lower_pin)"; IFS= read -r ACE_CC_LOWER_SENSOR_PIN || true
  printf '%s [1/2/3]: ' "$(t fiveway_question)"; IFS= read -r answer || answer=3
  case "$answer" in
    1)
      ACE_CC_PARKING_SENSOR=yes
      printf '%s: ' "$(t parking_pin)"; IFS= read -r ACE_CC_PARKING_SENSOR_PIN || true
      printf '%s [1/2]: ' "$(t parking_position)"; IFS= read -r position || position=1
      [ "$position" = "2" ] && ACE_CC_PARKING_SENSOR_POSITION=before_five_way || ACE_CC_PARKING_SENSOR_POSITION=after_five_way
      ;;
    2) ACE_CC_PARKING_SENSOR=no ;;
    *) ACE_CC_PARKING_SENSOR=later ;;
  esac
  export ACE_CC_UPPER_SENSOR_PIN ACE_CC_LOWER_SENSOR_PIN ACE_CC_PARKING_SENSOR ACE_CC_PARKING_SENSOR_PIN ACE_CC_PARKING_SENSOR_POSITION
}

prepare_config() {
  answer_mode=${1:-answers}
  GENERATED_CONFIG="${TMPDIR:-/tmp}/ace-pro-control-center-config-$$.cfg"
  cp "$PAYLOAD_CONFIG" "$GENERATED_CONFIG" || return 1
  if [ "$answer_mode" = "answers" ]; then
    upper=${ACE_CC_UPPER_SENSOR_PIN:-}
    lower=${ACE_CC_LOWER_SENSOR_PIN:-}
    parking=${ACE_CC_PARKING_SENSOR:-later}
    parking_pin=${ACE_CC_PARKING_SENSOR_PIN:-}
    parking_position=${ACE_CC_PARKING_SENSOR_POSITION:-after_five_way}
  else
    upper=''; lower=''; parking=later; parking_pin=''; parking_position=after_five_way
  fi
  valid_pin "$upper" && valid_pin "$lower" && valid_pin "$parking_pin" || {
    bad 'Invalid MCU pin syntax'; return 1;
  }
  case "$parking_position" in after_five_way|before_five_way) ;; *) bad 'Invalid parking sensor position'; return 1 ;; esac
  [ -z "$upper" ] || sed -i "s|^#extruder_sensor_pin:.*|extruder_sensor_pin: $upper|" "$GENERATED_CONFIG" || return 1
  [ -z "$lower" ] || sed -i "s|^#toolhead_sensor_pin:.*|toolhead_sensor_pin: $lower|" "$GENERATED_CONFIG" || return 1
  if [ "$parking" = "yes" ] && [ -n "$parking_pin" ]; then
    sed -i "s|^#parking_sensor_pin:.*|parking_sensor_pin: $parking_pin|" "$GENERATED_CONFIG" || return 1
  fi
  sed -i "s|^parking_sensor_position:.*|parking_sensor_position: $parking_position|" "$GENERATED_CONFIG" || return 1
  if [ "$answer_mode" = "answers" ] && { [ -z "$upper" ] || [ -z "$lower" ]; }; then
    warn "$(t config_required)"
  fi
}

require_file() { [ -f "$1" ] || { bad "Missing file: $1"; return 1; }; }
require_dir() { [ -d "$1" ] || { bad "Missing directory: $1"; return 1; }; }

verify_payload() {
  require_file "$PAYLOAD_DRIVER" && require_file "$PAYLOAD_CONFIG" &&
    require_file "$PAYLOAD_REQUIREMENTS" && require_dir "$PAYLOAD_FLUIDD" &&
    require_file "$PAYLOAD_FLUIDD/index.html" && require_file "$PAYLOAD_MOONRAKER" &&
    require_file "$PAYLOAD_WEB/ace.html" || return 1
  require_file "$ROOT_DIR/manifest.sha256" || return 1
  command -v sha256sum >/dev/null 2>&1 || {
    bad "sha256sum is required for payload verification"; return 1;
  }
  (cd "$ROOT_DIR" && sha256sum -c manifest.sha256 >/dev/null) || {
    bad "$(t payload_bad)"; return 1;
  }
}

compile_payload() {
  python_bin=''
  for candidate in "$KLIPPER_PYTHON" "$(command -v python3 2>/dev/null || true)" "$(command -v python 2>/dev/null || true)"; do
    [ -n "$candidate" ] || continue
    "$candidate" -c 'import sys' >/dev/null 2>&1 && { python_bin=$candidate; break; }
  done
  [ -z "$python_bin" ] || "$python_bin" -m py_compile "$PAYLOAD_DRIVER" "$PAYLOAD_MOONRAKER"
}

check_targets() {
  scope=$1
  case "$scope" in all|card)
    require_dir "$FLUIDD_ROOT" || return 1
    require_file "$FLUIDD_ROOT/index.html" || return 1
    require_dir "$MOONRAKER_ROOT/moonraker/components" || return 1
    require_file "$MOONRAKER_CONF" || return 1 ;;
  esac
  case "$scope" in all|driver)
    require_dir "$KLIPPER_ROOT/klippy/extras" || return 1
    require_file "$PRINTER_CFG" || return 1 ;;
  esac
}

frontend_has_risk() {
  current=$(normalize_version "$(detect_fluidd_version)")
  [ -n "$current" ] && [ "$(compare_versions "$current" "$TESTED_FLUIDD_VERSION")" = "0" ] || return 0
  moon=$(normalize_version "$(detect_moonraker_version)")
  [ -n "$moon" ] || return 0
  [ "$(compare_versions "$moon" "$TESTED_MOONRAKER_MIN_VERSION")" != "-1" ] || return 0
  [ "$(compare_versions "$moon" "$TESTED_MOONRAKER_MAX_VERSION")" != "1" ] || return 0
  return 1
}

resolve_compatibility() {
  scope=$1; force=$2
  [ "$scope" = "driver" ] && { printf '%s\n' driver; return; }
  frontend_has_risk || { printf '%s\n' "$scope"; return; }
  warn "$(t version_risk): Fluidd=$(detect_fluidd_version) (tested=$TESTED_FLUIDD_VERSION), Moonraker=$(detect_moonraker_version) (tested=$TESTED_MOONRAKER_MIN_VERSION..$TESTED_MOONRAKER_MAX_VERSION)"
  [ "$force" = "1" ] && { warn "$(t force_notice)"; printf '%s\n' "$scope"; return; }
  if [ "$YES" = "1" ]; then
    bad "$(t risk_noninteractive)"
    printf '%s\n' cancel
    return
  fi
  if [ "$scope" = "all" ]; then
    printf '%s: ' "$(t risk_choice)" >&2; IFS= read -r answer || answer=3
    case "$answer" in 1) printf '%s\n' driver ;; 2) printf '%s\n' all ;; *) printf '%s\n' cancel ;; esac
  else
    confirm "$(t version_risk). $(t confirm)" && printf '%s\n' card || printf '%s\n' cancel
  fi
}

fix_fluidd_permissions() { [ ! -d "$1" ] || chmod -R a+rX "$1"; }

archive_key_name() { printf '%s' "$1" | tr '/ ' '__'; }

verify_item_copy() {
  source=$1; copy=$2
  if [ -L "$source" ]; then
    [ -L "$copy" ] && [ "$(readlink "$source")" = "$(readlink "$copy")" ]
  elif [ -f "$source" ]; then
    [ -f "$copy" ] && [ ! -L "$copy" ] && cmp -s "$source" "$copy"
  elif [ -d "$source" ]; then
    [ -d "$copy" ] && [ ! -L "$copy" ] && diff -qr "$source" "$copy" >/dev/null
  else
    bad "Unsupported archive item: $source"
    return 1
  fi
}

archive_item() {
  archive=$1; key=$2; source=$3
  if path_exists "$source"; then
    mkdir -p "$archive/old/$(dirname -- "$key")" || return 1
    cp -a "$source" "$archive/old/$key" || return 1
    verify_item_copy "$source" "$archive/old/$key" || {
      bad "Archive verification failed: source=$source copy=$archive/old/$key"
      return 1
    }
    ARCHIVE_ITEM_INDEX=$((ARCHIVE_ITEM_INDEX + 1))
    if [ "${ACE_CC_TEST_FAIL_ARCHIVE_AT:-}" = "$ARCHIVE_ITEM_INDEX" ] || [ "${ACE_CC_TEST_FAIL_ARCHIVE_KEY:-}" = "$key" ]; then
      bad "Injected archive failure: key=$key source=$source archive=$archive"
      return 1
    fi
    : > "$archive/present.$(archive_key_name "$key")" || return 1
  fi
}

create_archive() {
  archive=$1; scope=$2
  ARCHIVE_ITEM_INDEX=0
  mkdir -p "$archive/old" "$archive/resolved" || return 1
  {
    printf 'app_id=%s\npackage_version=%s\nscope=%s\nlanguage=%s\n' "$APP_ID" "$PACKAGE_VERSION" "$scope" "$LANG_CODE"
    printf 'fluidd_root=%s\nklipper_root=%s\nmoonraker_root=%s\nace_root=%s\n' "$FLUIDD_ROOT" "$KLIPPER_ROOT" "$MOONRAKER_ROOT" "$ACE_CC_ROOT"
  } > "$archive/manifest.txt" || return 1
  case "$scope" in all|driver)
    if path_exists "$TARGET_CONFIG_LINK"; then cp -L "$TARGET_CONFIG_LINK" "$archive/resolved/current-ace.cfg" || return 1
    elif path_exists "$TARGET_CONFIG_ROOT"; then cp -L "$TARGET_CONFIG_ROOT" "$archive/resolved/current-ace.cfg" || return 1; fi ;;
  esac
  case "$scope" in all|card)
    archive_item "$archive" fluidd "$FLUIDD_ROOT" || return 1
    archive_item "$archive" moonraker/ace_status.py "$TARGET_COMPONENT" || return 1
    archive_item "$archive" moonraker/moonraker.conf "$MOONRAKER_CONF" || return 1
    archive_item "$archive" ace-web "$TARGET_WEB" || return 1 ;;
  esac
  case "$scope" in all|driver)
    archive_item "$archive" klipper-driver/ace.py "$TARGET_DRIVER_LINK" || return 1
    archive_item "$archive" ace-root-driver/ace.py "$TARGET_DRIVER_ROOT" || return 1
    archive_item "$archive" printer-config/ace.cfg "$TARGET_CONFIG_LINK" || return 1
    archive_item "$archive" ace-root-config/ace.cfg "$TARGET_CONFIG_ROOT" || return 1
    archive_item "$archive" ace-root-config/ace.cfg.example "$ACE_CC_ROOT/ace.cfg.example" || return 1
    archive_item "$archive" ace-root-config/requirements.txt "$ACE_CC_ROOT/requirements.txt" || return 1
    archive_item "$archive" printer-config/printer.cfg "$PRINTER_CFG" || return 1 ;;
  esac
  archive_item "$archive" state/installed "$MARKER" || return 1
  : > "$archive/archive.complete" || return 1
}

archive_scope() { sed -n 's/^scope=//p' "$1/manifest.txt" | tail -n 1; }
baseline_file() { case "$1" in all) printf '%s\n' "$BASELINE_FILE" ;; driver) printf '%s\n' "$DRIVER_BASELINE_FILE" ;; card) printf '%s\n' "$CARD_BASELINE_FILE" ;; esac; }

restore_item() {
  archive=$1; quarantine=$2; key=$3; target=$4
  marker="$archive/present.$(archive_key_name "$key")"
  RESTORE_ITEM_INDEX=$((RESTORE_ITEM_INDEX + 1))
  target_parent=$(dirname -- "$target")
  target_name=$(basename -- "$target")
  stage="$target_parent/.${target_name}.${APP_ID}-restore-$$-$RESTORE_ITEM_INDEX"
  had_target=0
  if [ -f "$marker" ]; then
    path_exists "$archive/old/$key" || {
      bad "Restore source missing: target=$target archive=$archive quarantine=$quarantine"
      return 1
    }
    mkdir -p "$target_parent" || return 1
    cp -a "$archive/old/$key" "$stage" || {
      bad "Restore staging failed: target=$target archive=$archive quarantine=$quarantine"
      return 1
    }
    verify_item_copy "$archive/old/$key" "$stage" || {
      bad "Restore verification failed: target=$target archive=$archive quarantine=$quarantine"
      return 1
    }
  fi
  if [ "${ACE_CC_TEST_FAIL_RESTORE_AT:-}" = "$RESTORE_ITEM_INDEX" ] || [ "${ACE_CC_TEST_FAIL_RESTORE_KEY:-}" = "$key" ]; then
    bad "Injected restore failure: target=$target archive=$archive quarantine=$quarantine"
    return 1
  fi
  if path_exists "$target"; then
    had_target=1
    mkdir -p "$quarantine/$(dirname -- "$key")" || return 1
    mv "$target" "$quarantine/$key" || return 1
  fi
  if [ -f "$marker" ]; then
    if ! mv "$stage" "$target"; then
      bad "Restore replacement failed: target=$target archive=$archive quarantine=$quarantine"
      if [ "$had_target" = "1" ] && ! mv "$quarantine/$key" "$target"; then
        bad "Restore rollback failed: target=$target archive=$archive quarantine=$quarantine"
      fi
      return 1
    fi
  fi
}

restore_archive() {
  archive=$1; quarantine=${2:-"$archive/restore-quarantine-$$"}; requested_scope=${3:-}; restore_state=${4:-1}
  [ -f "$archive/archive.complete" ] || { bad "Incomplete archive: $archive"; return 1; }
  scope=$requested_scope
  [ -n "$scope" ] || scope=$(archive_scope "$archive")
  [ -n "$scope" ] || scope=all
  case "$scope" in all|driver|card) ;; *) bad "Invalid restore scope: $scope"; return 1 ;; esac
  mkdir -p "$quarantine" || return 1
  case "$scope" in all|card)
    restore_item "$archive" "$quarantine" fluidd "$FLUIDD_ROOT" || return 1
    restore_item "$archive" "$quarantine" moonraker/ace_status.py "$TARGET_COMPONENT" || return 1
    restore_item "$archive" "$quarantine" moonraker/moonraker.conf "$MOONRAKER_CONF" || return 1
    restore_item "$archive" "$quarantine" ace-web "$TARGET_WEB" || return 1
    fix_fluidd_permissions "$FLUIDD_ROOT" || return 1 ;;
  esac
  case "$scope" in all|driver)
    restore_item "$archive" "$quarantine" ace-root-driver/ace.py "$TARGET_DRIVER_ROOT" || return 1
    restore_item "$archive" "$quarantine" klipper-driver/ace.py "$TARGET_DRIVER_LINK" || return 1
    restore_item "$archive" "$quarantine" ace-root-config/ace.cfg "$TARGET_CONFIG_ROOT" || return 1
    restore_item "$archive" "$quarantine" ace-root-config/ace.cfg.example "$ACE_CC_ROOT/ace.cfg.example" || return 1
    restore_item "$archive" "$quarantine" ace-root-config/requirements.txt "$ACE_CC_ROOT/requirements.txt" || return 1
    restore_item "$archive" "$quarantine" printer-config/ace.cfg "$TARGET_CONFIG_LINK" || return 1
    restore_item "$archive" "$quarantine" printer-config/printer.cfg "$PRINTER_CFG" || return 1 ;;
  esac
  [ "$restore_state" = "0" ] || restore_item "$archive" "$quarantine" state/installed "$MARKER" || return 1
}

begin_transaction() {
  TRANSACTION_ARCHIVE=$1
  TRANSACTION_ACTIVE=1
  TRANSACTION_RECOVERING=0
  TRANSACTION_RECOVERY_FAILED=0
}

finish_transaction() {
  TRANSACTION_ARCHIVE=""
  TRANSACTION_ACTIVE=0
  TRANSACTION_RECOVERING=0
  TRANSACTION_RECOVERY_FAILED=0
}

recover_transaction() {
  label=$1
  [ "$TRANSACTION_ACTIVE" = "1" ] || return 0
  TRANSACTION_RECOVERING=1
  quarantine="$TRANSACTION_ARCHIVE/$label-quarantine-$$"
  if restore_archive "$TRANSACTION_ARCHIVE" "$quarantine"; then
    finish_transaction
    return 0
  fi
  TRANSACTION_RECOVERING=0
  TRANSACTION_RECOVERY_FAILED=1
  bad "Transaction recovery failed: archive=$TRANSACTION_ARCHIVE quarantine=$quarantine"
  return 1
}

replace_active_item() {
  archive=$1; key=$2; target=$3
  path_exists "$target" || return 0
  REPLACE_ITEM_INDEX=$((REPLACE_ITEM_INDEX + 1))
  replaced="$archive/replaced/$key"
  mkdir -p "$(dirname -- "$replaced")" || return 1
  if [ "${ACE_CC_TEST_FAIL_REPLACE_AT:-}" = "$REPLACE_ITEM_INDEX" ] || [ "${ACE_CC_TEST_FAIL_REPLACE_KEY:-}" = "$key" ]; then
    bad "Injected replacement failure: key=$key target=$target archive=$archive"
    return 1
  fi
  mv "$target" "$replaced" || return 1
  if [ "${ACE_CC_TEST_SIGNAL_AFTER_REPLACE_AT:-}" = "$REPLACE_ITEM_INDEX" ]; then
    kill -TERM "$$"
  fi
}

append_section() {
  file=$1; section=$2; body=$3
  grep -Eq "^[[:space:]]*\\[$section\\][[:space:]]*$" "$file" && return 0
  printf '\n# Added by %s %s\n[%s]\n%s\n' "$APP_ID" "$PACKAGE_VERSION" "$section" "$body" >> "$file" || return 1
}

install_dependencies() {
  [ "${ACE_CC_SKIP_DEPENDENCIES:-0}" = "1" ] && return 0
  if [ -x "$KLIPPER_PYTHON" ] && ! "$KLIPPER_PYTHON" -c 'import serial' >/dev/null 2>&1; then
    "$KLIPPER_PYTHON" -m pip install 'pyserial==3.5'
  fi
}

install_driver_files() {
  archive=$1; config_mode=$2
  config_source=$GENERATED_CONFIG
  mkdir -p "$ACE_CC_ROOT/extras" "$KLIPPER_ROOT/klippy/extras" "$PRINTER_CONFIG_DIR" || return 1
  REPLACE_ITEM_INDEX=0
  replace_active_item "$archive" ace-root-driver/ace.py "$TARGET_DRIVER_ROOT" || return 1
  cp -a "$PAYLOAD_DRIVER" "$TARGET_DRIVER_ROOT" || return 1
  replace_active_item "$archive" klipper-driver/ace.py "$TARGET_DRIVER_LINK" || return 1
  ln -s "$TARGET_DRIVER_ROOT" "$TARGET_DRIVER_LINK" || return 1
  if [ "$config_mode" = preserve ] && [ -f "$archive/resolved/current-ace.cfg" ]; then
    config_source="$archive/resolved/current-ace.cfg"
  fi
  replace_active_item "$archive" ace-root-config/ace.cfg "$TARGET_CONFIG_ROOT" || return 1
  cp "$config_source" "$TARGET_CONFIG_ROOT" || return 1
  replace_active_item "$archive" printer-config/ace.cfg "$TARGET_CONFIG_LINK" || return 1
  cp "$config_source" "$TARGET_CONFIG_LINK" || return 1
  chmod u+rw,go+r "$TARGET_CONFIG_ROOT" "$TARGET_CONFIG_LINK" || return 1
  [ -f "$TARGET_CONFIG_LINK" ] && [ ! -L "$TARGET_CONFIG_LINK" ] || return 1
  replace_active_item "$archive" ace-root-config/ace.cfg.example "$ACE_CC_ROOT/ace.cfg.example" || return 1
  cp -a "$GENERATED_CONFIG" "$ACE_CC_ROOT/ace.cfg.example" || return 1
  replace_active_item "$archive" ace-root-config/requirements.txt "$ACE_CC_ROOT/requirements.txt" || return 1
  cp -a "$PAYLOAD_REQUIREMENTS" "$ACE_CC_ROOT/requirements.txt" || return 1
  replace_active_item "$archive" printer-config/printer.cfg "$PRINTER_CFG" || return 1
  cp -a "$archive/old/printer-config/printer.cfg" "$PRINTER_CFG" || return 1
  append_section "$PRINTER_CFG" 'include ace.cfg' '' || return 1
  install_dependencies || return 1
}

install_card_files() {
  archive=$1; parent=$(dirname -- "$FLUIDD_ROOT"); name=$(basename -- "$FLUIDD_ROOT"); stage="$parent/.${name}.${APP_ID}-stage-$$"
  mkdir -p "$ACE_CC_ROOT/ace_status_integration" "$MOONRAKER_ROOT/moonraker/components" || return 1
  cp -a "$PAYLOAD_FLUIDD" "$stage" || return 1
  [ ! -f "$archive/old/fluidd/config.json" ] || cp -a "$archive/old/fluidd/config.json" "$stage/config.json" || return 1
  cp -a "$PAYLOAD_WEB/." "$stage/" || return 1
  REPLACE_ITEM_INDEX=0
  replace_active_item "$archive" fluidd "$FLUIDD_ROOT" || return 1
  mv "$stage" "$FLUIDD_ROOT" || return 1
  fix_fluidd_permissions "$FLUIDD_ROOT" || return 1
  replace_active_item "$archive" moonraker/ace_status.py "$TARGET_COMPONENT" || return 1
  cp -a "$PAYLOAD_MOONRAKER" "$TARGET_COMPONENT" || return 1
  replace_active_item "$archive" ace-web "$TARGET_WEB" || return 1
  cp -a "$PAYLOAD_WEB" "$TARGET_WEB" || return 1
  replace_active_item "$archive" moonraker/moonraker.conf "$MOONRAKER_CONF" || return 1
  cp -a "$archive/old/moonraker/moonraker.conf" "$MOONRAKER_CONF" || return 1
  append_section "$MOONRAKER_CONF" ace_status 'upper_sensor_name: extruder_sensor
lower_sensor_name: toolhead_sensor' || return 1
}

new_archive_path() { printf '%s/%s-%s\n' "$OLD_ROOT" "$(date +%Y%m%d-%H%M%S)" "$$-$1"; }

prepare_global_baseline() {
  requested_scope=$1
  GLOBAL_BASELINE_CANDIDATE=""
  [ -s "$BASELINE_FILE" ] && return 0
  if [ -s "$MARKER" ] || [ -s "$DRIVER_BASELINE_FILE" ] || [ -s "$CARD_BASELINE_FILE" ]; then
    bad "Global first-install baseline is missing for an existing installation: $STATE_DIR"
    return 1
  fi
  GLOBAL_BASELINE_CANDIDATE=$(new_archive_path baseline)
  create_archive "$GLOBAL_BASELINE_CANDIDATE" all || {
    bad "Global baseline archive failed: $GLOBAL_BASELINE_CANDIDATE"
    return 1
  }
  [ "$requested_scope" != all ] || OPERATION_ARCHIVE="$GLOBAL_BASELINE_CANDIDATE"
}

record_baselines() {
  scope=$1; operation_archive=$2
  if [ -n "${GLOBAL_BASELINE_CANDIDATE:-}" ] && [ ! -s "$BASELINE_FILE" ]; then
    printf '%s\n' "$GLOBAL_BASELINE_CANDIDATE" > "$BASELINE_FILE" || return 1
  fi
  component_baseline=$(baseline_file "$scope")
  if [ ! -s "$component_baseline" ]; then
    printf '%s\n' "$operation_archive" > "$component_baseline" || return 1
  fi
  if [ "$scope" = "all" ]; then
    [ -s "$DRIVER_BASELINE_FILE" ] || printf '%s\n' "$operation_archive" > "$DRIVER_BASELINE_FILE" || return 1
    [ -s "$CARD_BASELINE_FILE" ] || printf '%s\n' "$operation_archive" > "$CARD_BASELINE_FILE" || return 1
  fi
}

install_suite() {
  force=${1:-0}; requested_scope=${2:-all}; config_mode=${3:-preserve}
  require_non_root || return 1
  require_valid_config_mode "$config_mode" || return 1
  require_safe_layout || return 1
  verify_payload || return 1
  compile_payload || return 1
  check_targets "$requested_scope" || return 1
  scope=$(resolve_compatibility "$requested_scope" "$force") || return 1
  [ "$scope" != cancel ] || { warn "$(t cancelled)"; return 1; }
  case "$scope" in all|driver)
    if [ "$config_mode" = "preserve" ] && { path_exists "$TARGET_CONFIG_LINK" || path_exists "$TARGET_CONFIG_ROOT"; }; then
      warn "$(t config_preserved)"
      prepare_config defaults || return 1
    else
      collect_config_answers || return 1
      prepare_config answers || return 1
    fi ;;
  esac
  effective_scope=$scope
  OPERATION_ARCHIVE=""
  prepare_global_baseline "$effective_scope" || return 1
  archive=${OPERATION_ARCHIVE:-$(new_archive_path operation)}
  if [ "$archive" != "${GLOBAL_BASELINE_CANDIDATE:-}" ]; then
    create_archive "$archive" "$effective_scope" || { bad "$(t archive_failed): $archive"; return 1; }
  fi
  scope=$effective_scope
  begin_transaction "$archive"
  install_result=0
  case "$scope" in all|driver) install_driver_files "$archive" "$config_mode" || install_result=1 ;; esac
  if [ "$install_result" = "0" ]; then
    case "$scope" in all|card) install_card_files "$archive" || install_result=1 ;; esac
  fi
  if [ "$install_result" = "0" ]; then
    mkdir -p "$STATE_DIR" || install_result=1
    if [ "$install_result" = "0" ]; then
      printf 'app_id=%s\npackage_version=%s\nscope=%s\nlanguage=%s\nconfig_mode=%s\nold_archive=%s\n' "$APP_ID" "$PACKAGE_VERSION" "$scope" "$LANG_CODE" "$config_mode" "$archive" > "$MARKER" || install_result=1
    fi
    if [ "$install_result" = "0" ]; then
      record_baselines "$effective_scope" "$archive" || install_result=1
    fi
  fi
  if [ "$install_result" = "0" ]; then
    finish_transaction
    case "$effective_scope" in all) ok "$(t install_ok_all)" ;; driver) ok "$(t install_ok_driver)" ;; card) ok "$(t install_ok_card)" ;; esac
    case "$effective_scope" in all|driver) ok "$(t config_editable)" ;; esac
    ok "$(t rollback_hint)"; warn "$(t restart_notice)"
  else
    if recover_transaction install-failure; then
      bad "$(t install_failed)"
    else
      bad "$(t install_failed): archive=$archive"
    fi
    return 1
  fi
}

rollback_latest() {
  require_non_root || return 1
  require_safe_layout || return 1
  [ -s "$MARKER" ] || { bad "$(t no_baseline)"; return 1; }
  previous=$(sed -n 's/^old_archive=//p' "$MARKER" | tail -n 1); [ -f "$previous/archive.complete" ] || { bad "$(t no_baseline)"; return 1; }
  scope=$(archive_scope "$previous"); current=$(new_archive_path rollback)
  create_archive "$current" "$scope" || { bad "Rollback archive failed: $current"; return 1; }
  begin_transaction "$current"
  if restore_archive "$previous" "$current/rollback-quarantine"; then
    finish_transaction
    ok "$(t rollback_ok)"
  else
    recover_transaction rollback-failure || return 1
    return 1
  fi
}

uninstall_suite() {
  scope=${1:-all}; baseline_path=$(baseline_file "$scope")
  require_non_root || return 1
  require_safe_layout || return 1
  combined=0
  if [ "$scope" != "all" ] && [ ! -s "$baseline_path" ] && [ -s "$BASELINE_FILE" ]; then
    baseline_path=$BASELINE_FILE
  fi
  if [ "$scope" = "all" ] && [ ! -s "$baseline_path" ]; then
    if [ -s "$DRIVER_BASELINE_FILE" ] || [ -s "$CARD_BASELINE_FILE" ]; then
      combined=1
    else
      bad "$(t no_baseline)"; return 1
    fi
  elif [ ! -s "$baseline_path" ]; then
    bad "$(t no_baseline)"; return 1
  fi
  if [ "$combined" = "0" ]; then
    baseline=$(sed -n '1p' "$baseline_path")
    [ -f "$baseline/archive.complete" ] || { bad "$(t no_baseline)"; return 1; }
  fi
  current=$(new_archive_path uninstall)
  create_archive "$current" "$scope" || { bad "Uninstall archive failed: $current"; return 1; }
  begin_transaction "$current"
  restore_result=0
  if [ "$combined" = "1" ]; then
    if [ -s "$DRIVER_BASELINE_FILE" ]; then
      driver_baseline=$(sed -n '1p' "$DRIVER_BASELINE_FILE")
      [ -f "$driver_baseline/archive.complete" ] || restore_result=1
      [ "$restore_result" = "1" ] || restore_archive "$driver_baseline" "$current/uninstall-driver-quarantine" || restore_result=1
    fi
    if [ "$restore_result" = "0" ] && [ -s "$CARD_BASELINE_FILE" ]; then
      card_baseline=$(sed -n '1p' "$CARD_BASELINE_FILE")
      [ -f "$card_baseline/archive.complete" ] || restore_result=1
      [ "$restore_result" = "1" ] || restore_archive "$card_baseline" "$current/uninstall-card-quarantine" || restore_result=1
    fi
  elif [ "$scope" = "all" ]; then
    restore_archive "$baseline" "$current/uninstall-quarantine" || restore_result=1
  else
    restore_archive "$baseline" "$current/uninstall-quarantine" "$scope" 0 || restore_result=1
  fi
  if [ "$restore_result" != "0" ]; then
    recover_transaction uninstall-failure || return 1
    return 1
  fi
  if [ "$scope" = "all" ]; then
    [ ! -f "$MARKER" ] || mv "$MARKER" "$STATE_DIR/installed.uninstalled.$(date +%Y%m%d-%H%M%S)" || return 1
  else
    printf 'app_id=%s\npackage_version=%s\nscope=%s\nlanguage=%s\nconfig_mode=restore\nold_archive=%s\n' \
      "$APP_ID" "$PACKAGE_VERSION" "$scope" "$LANG_CODE" "$current" > "$MARKER" || return 1
  fi
  finish_transaction
  ok "$(t uninstall_ok)"
}

show_status() {
  header
  printf 'Fluidd: %s\nDriver: %s\nConfig: %s\nMoonraker: %s\nArchive: %s\n' "$FLUIDD_ROOT" "$TARGET_DRIVER_LINK" "$TARGET_CONFIG_LINK" "$TARGET_COMPONENT" "$OLD_ROOT"
  if [ -L "$TARGET_CONFIG_LINK" ]; then
    printf 'Config mode: %s\n' "$(t config_mode_locked)"
  elif [ -f "$TARGET_CONFIG_LINK" ] && [ -w "$TARGET_CONFIG_LINK" ]; then
    printf 'Config mode: %s\n' "$(t config_mode_editable)"
  elif [ -f "$TARGET_CONFIG_LINK" ]; then
    printf 'Config mode: read-only regular file\n'
  else
    printf 'Config mode: %s\n' "$(t config_mode_missing)"
  fi
  if [ -f "$TARGET_CONFIG_LINK" ]; then
    grep -Eq '^[[:space:]]*parking_sensor_pin:' "$TARGET_CONFIG_LINK" && printf 'Five-way sensor: enabled\n' || printf 'Five-way sensor: disabled / pending\n'
  fi
}

pause_menu() { printf '\n%s' "$(t press_enter)"; IFS= read -r _answer || true; }

run_cli_action() {
  confirm "$(t confirm)" || { warn "$(t cancelled)"; return 1; }
  "$@"
}

show_help() {
  cat <<'EOF'
Usage: sh ui-installer.sh [--yes] ACTION

Actions:
  --install              Install/update driver, configuration, Moonraker and Fluidd
  --install-driver       Install/update driver and configuration only
  --install-card         Install/update Fluidd, Moonraker component and fallback page only
  --install-new-config   Complete install and replace runtime ace.cfg with the new template
  --install-force        Complete install while explicitly accepting compatibility risk
  --rollback-latest      Restore the state before the latest recorded operation
  --uninstall            Restore the global first-write baseline
  --uninstall-driver     Restore only the driver/configuration first-write baseline
  --uninstall-card       Restore only the Fluidd/Moonraker first-write baseline
  --status               Show paths, versions and installation state (read-only)
  --help, -h             Show this help (read-only)

Options:
  --yes                  Skip action confirmation; must appear before ACTION

Key environment variables:
  ACE_CC_LANG, ACE_CC_CONFIG_MODE
  ACE_CC_UPPER_SENSOR_PIN, ACE_CC_LOWER_SENSOR_PIN
  ACE_CC_PARKING_SENSOR, ACE_CC_PARKING_SENSOR_PIN, ACE_CC_PARKING_SENSOR_POSITION
  FLUIDD_ROOT, KLIPPER_ROOT, KLIPPER_PYTHON, MOONRAKER_ROOT
  PRINTER_CONFIG_DIR, PRINTER_CFG, MOONRAKER_CONF
  ACE_CC_ROOT, ACE_CC_STATE_DIR
EOF
}

menu() {
  choose_language
  while true; do
    header
    printf '1. %s\n2. %s\n3. %s\n4. %s\n5. %s\n6. %s\n7. %s\n8. %s\n' \
      "$(t menu_install_all)" "$(t menu_install_driver)" "$(t menu_install_card)" "$(t menu_force)" \
      "$(t menu_rollback)" "$(t menu_uninstall)" "$(t menu_status)" "$(t menu_exit)"
    printf '%s [1-8]: ' "$(t choose)"; IFS= read -r choice || exit 0
    case "$choice" in
      1) confirm "$(t confirm)" && install_suite 0 all preserve || true; pause_menu ;;
      2) confirm "$(t confirm)" && install_suite 0 driver preserve || true; pause_menu ;;
      3) confirm "$(t confirm)" && install_suite 0 card preserve || true; pause_menu ;;
      4) confirm "$(t confirm)" && install_suite 1 all preserve || true; pause_menu ;;
      5) confirm "$(t confirm)" && rollback_latest || true; pause_menu ;;
      6) confirm "$(t confirm)" && uninstall_suite all || true; pause_menu ;;
      7) show_status; pause_menu ;;
      8) exit 0 ;;
      *) pause_menu ;;
    esac
  done
}

if [ "${1:-}" = "--yes" ]; then YES=1; shift; fi
case "${1:-}" in
  --install) run_cli_action install_suite 0 all "${ACE_CC_CONFIG_MODE:-preserve}" ;;
  --install-driver) run_cli_action install_suite 0 driver "${ACE_CC_CONFIG_MODE:-preserve}" ;;
  --install-card) run_cli_action install_suite 0 card preserve ;;
  --install-new-config) run_cli_action install_suite 0 all replace ;;
  --install-force) run_cli_action install_suite 1 all "${ACE_CC_CONFIG_MODE:-preserve}" ;;
  --rollback-latest) run_cli_action rollback_latest ;;
  --uninstall) run_cli_action uninstall_suite all ;;
  --uninstall-driver) run_cli_action uninstall_suite driver ;;
  --uninstall-card) run_cli_action uninstall_suite card ;;
  --status) show_status ;;
  --help|-h) show_help ;;
  '') menu ;;
  *) bad "Unknown argument: $1"; exit 2 ;;
esac
