#!/usr/bin/env sh
set -eu

APP_NAME="ACEPROSV08 驱动 + Fluidd 卡片一体化安装器"
REPOSITORY_URL="https://github.com/Luomo520/fluidd-acepro-card-ACEPROSV08"
TESTED_FLUIDD_VERSION="1.37.2"
ROOT_DIR=$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)
PACKAGE_VERSION=$(sed -n '1p' "$ROOT_DIR/VERSION" 2>/dev/null || printf 'unknown')

FLUIDD_ROOT=${FLUIDD_ROOT:-"$HOME/fluidd"}
KLIPPER_ROOT=${KLIPPER_ROOT:-"$HOME/klipper"}
KLIPPER_PYTHON=${KLIPPER_PYTHON:-"$HOME/klippy-env/bin/python"}
MOONRAKER_ROOT=${MOONRAKER_ROOT:-"$HOME/moonraker"}
PRINTER_CONFIG_DIR=${PRINTER_CONFIG_DIR:-"$HOME/printer_data/config"}
PRINTER_CFG=${PRINTER_CFG:-"$PRINTER_CONFIG_DIR/printer.cfg"}
MOONRAKER_CONF=${MOONRAKER_CONF:-"$PRINTER_CONFIG_DIR/moonraker.conf"}
ACEPRO_ROOT=${ACEPRO_ROOT:-"$HOME/ACEPROSV08"}
STATE_DIR=${ACEPROSV08_UI_STATE_DIR:-"$HOME/.local/share/aceprosv08-ui"}
OLD_ROOT="$STATE_DIR/old"
BASELINE_FILE="$STATE_DIR/first_install_old"
DRIVER_BASELINE_FILE="$STATE_DIR/first_install_old_driver"
CARD_BASELINE_FILE="$STATE_DIR/first_install_old_card"
MARKER="$STATE_DIR/installed"

PAYLOAD_DRIVER="$ROOT_DIR/extras/ace.py"
PAYLOAD_CONFIG="$ROOT_DIR/ace.cfg"
PAYLOAD_REQUIREMENTS="$ROOT_DIR/requirements.txt"
PAYLOAD_FLUIDD="$ROOT_DIR/fluidd-dist"
PAYLOAD_MOONRAKER="$ROOT_DIR/ace_status_integration/moonraker/ace_status.py"
PAYLOAD_WEB="$ROOT_DIR/ace_status_integration/web"

TARGET_DRIVER_ROOT="$ACEPRO_ROOT/extras/ace.py"
TARGET_DRIVER_LINK="$KLIPPER_ROOT/klippy/extras/ace.py"
TARGET_CONFIG_ROOT="$ACEPRO_ROOT/ace.cfg"
TARGET_CONFIG_LINK="$PRINTER_CONFIG_DIR/ace.cfg"
TARGET_COMPONENT="$MOONRAKER_ROOT/moonraker/components/ace_status.py"
TARGET_WEB="$ACEPRO_ROOT/ace_status_integration/web"

ok() { printf '[  OK  ] %s\n' "$1"; }
warn() { printf '[ 警告 ] %s\n' "$1" >&2; }
bad() { printf '[ 失败 ] %s\n' "$1" >&2; }
line() { printf '%s\n' '+------------------------------------------------------------------------+'; }
path_exists() { [ -e "$1" ] || [ -L "$1" ]; }

first_line() {
  if [ -s "$1" ]; then
    IFS= read -r value < "$1" || true
    printf '%s\n' "${value:-未知}"
  else
    printf '%s\n' '未知'
  fi
}

detect_fluidd_version() { first_line "$FLUIDD_ROOT/.version"; }

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
    value=$(sed -n 's/^ACEPROSV08_DRIVER_VERSION = ["'"']\([^"'"']*\)["'"'].*/\1/p' "$driver" 2>/dev/null | head -n 1)
    [ -n "$value" ] && printf '%s\n' "$value" || printf '%s\n' '已安装（上游版/未知版本）'
  else
    printf '%s\n' '未安装'
  fi
}

detect_api_status() {
  if command -v curl >/dev/null 2>&1; then
    code=$(curl -sS -o /dev/null -w '%{http_code}' --max-time 4 http://127.0.0.1:7125/server/ace/status 2>/dev/null || true)
    [ "$code" = "200" ] && printf '%s\n' '可访问' || printf '暂不可访问（HTTP %s）\n' "${code:-无响应}"
  else
    printf '%s\n' '未检测（缺少 curl）'
  fi
}

latest_old() {
  if [ -d "$OLD_ROOT" ]; then
    find "$OLD_ROOT" -mindepth 1 -maxdepth 1 -type d -name '20*' 2>/dev/null | sort | tail -n 1 | sed 's#^.*/##'
  fi
}

detect_install_state() {
  [ -f "$MARKER" ] && printf '%s\n' '已安装' || printf '%s\n' '未由本安装器安装'
}

header() {
  command -v clear >/dev/null 2>&1 && clear || true
  line
  printf '| %-70s |\n' "$APP_NAME"
  line
  printf '  Fluidd 版本      : %s\n' "$(detect_fluidd_version)"
  printf '  驱动版本         : %s\n' "$(detect_driver_version)"
  printf '  安装包版本       : %s\n' "$PACKAGE_VERSION"
  printf '  ACE API          : %s\n' "$(detect_api_status)"
  printf '  安装状态         : %s\n' "$(detect_install_state)"
  printf '  最近 old 归档    : %s\n' "$(latest_old || printf '无')"
  line
}

pause_menu() {
  printf '\n按 Enter 返回菜单...'
  IFS= read -r _answer || true
}

confirm() {
  [ "${YES:-0}" = "1" ] && return 0
  printf '%s [y/N]: ' "$1"
  IFS= read -r answer || return 1
  case "$answer" in y|Y|yes|YES) return 0 ;; *) return 1 ;; esac
}

require_file() { [ -f "$1" ] || { bad "缺少文件: $1"; return 1; }; }
require_dir() { [ -d "$1" ] || { bad "缺少目录: $1"; return 1; }; }

fix_fluidd_permissions() {
  [ -d "$1" ] || return 0
  chmod -R a+rX "$1" || {
    bad "无法设置 Fluidd 的 Web 可读权限: $1"
    return 1
  }
}

verify_payload() {
  require_file "$PAYLOAD_DRIVER"
  require_file "$PAYLOAD_CONFIG"
  require_file "$PAYLOAD_REQUIREMENTS"
  require_dir "$PAYLOAD_FLUIDD"
  require_file "$PAYLOAD_FLUIDD/index.html"
  require_file "$PAYLOAD_MOONRAKER"
  require_file "$PAYLOAD_WEB/ace.html"
  require_file "$PAYLOAD_WEB/ace-dashboard.js"
  require_file "$PAYLOAD_WEB/ace-dashboard.css"

  if command -v sha256sum >/dev/null 2>&1 && [ -f "$ROOT_DIR/manifest.sha256" ]; then
    (cd "$ROOT_DIR" && sha256sum -c manifest.sha256 >/dev/null) || {
      bad "安装文件校验失败，请重新通过 Git 下载完整仓库"
      return 1
    }
  else
    warn "缺少 sha256sum 或校验清单，仅完成基础文件检查"
  fi
}

check_install_targets() {
  scope=$1
  case "$scope" in
    all|card)
      require_dir "$FLUIDD_ROOT"
      require_file "$FLUIDD_ROOT/index.html"
      require_dir "$MOONRAKER_ROOT/moonraker/components"
      require_file "$MOONRAKER_CONF"
      ;;
  esac
  case "$scope" in
    all|driver)
      require_dir "$KLIPPER_ROOT/klippy/extras"
      require_file "$PRINTER_CFG"
      ;;
  esac
}

check_environment() {
  scope=$1
  case "$scope" in
    all|driver)
      if path_exists "$TARGET_DRIVER_LINK" && ! grep -q 'class BunnyAce' "$TARGET_DRIVER_LINK" 2>/dev/null; then
        warn "当前 Klipper ace.py 不是可识别的 ACEPROSV08 驱动；它仍会进入 old 归档"
      fi
      if grep -Rqs 'filament_runout_sensor_name_rdm' "$PRINTER_CONFIG_DIR" 2>/dev/null; then
        warn "配置目录中检测到 Kobra-S1 驱动字段，请确认没有同时 include 旧配置"
      fi
      ;;
  esac
  case "$scope" in
    all|card)
      if command -v curl >/dev/null 2>&1; then
        code=$(curl -sS -o /dev/null -w '%{http_code}' --max-time 4 http://127.0.0.1:7125/server/info 2>/dev/null || true)
        [ "$code" = "200" ] || warn "Moonraker 当前不可访问（HTTP ${code:-无响应}），安装后需人工检查服务"
      fi
      ;;
  esac
}

check_fluidd_compatibility() {
  raw=$(detect_fluidd_version)
  current=$(normalize_version "$raw")
  if [ -z "$current" ]; then
    warn "无法识别当前 Fluidd 版本（检测值: $raw）"
    confirm "继续安装内置 Fluidd v$TESTED_FLUIDD_VERSION，并保留可回滚归档吗？" || return 1
    return 0
  fi

  relation=$(compare_versions "$current" "$TESTED_FLUIDD_VERSION")
  case "$relation" in
    0) ok "当前 Fluidd v$current 与本包测试版本一致" ;;
    -1)
      warn "当前 Fluidd v$current 低于测试版本 v$TESTED_FLUIDD_VERSION；继续后界面会升级，旧主题或配置可能需要调整"
      confirm "继续安装并保留回滚到 Fluidd v$current 的可能吗？" || return 1
      ;;
    1)
      warn "当前 Fluidd v$current 高于测试版本 v$TESTED_FLUIDD_VERSION；继续后界面会降级，较新 Fluidd 功能可能暂时不可用"
      confirm "仍要安装，并保留回滚到 Fluidd v$current 的可能吗？" || return 1
      ;;
  esac
}

compile_python_payload() {
  python_bin=''
  for candidate in "$KLIPPER_PYTHON" "$(command -v python3 2>/dev/null || true)" "$(command -v python 2>/dev/null || true)"; do
    [ -n "$candidate" ] || continue
    if "$candidate" -c 'import sys' >/dev/null 2>&1; then
      python_bin=$candidate
      break
    fi
  done
  if [ -n "$python_bin" ]; then
    "$python_bin" -m py_compile "$PAYLOAD_DRIVER" "$PAYLOAD_MOONRAKER" || {
      bad "Python 编译检查失败"
      return 1
    }
  else
    warn "未找到 Python，跳过离线编译检查"
  fi
}

archive_item() {
  archive=$1
  key=$2
  source=$3
  if path_exists "$source"; then
    mkdir -p "$archive/old/$(dirname -- "$key")" || return 1
    : > "$archive/present.$(printf '%s' "$key" | tr '/' '_')"
    mv "$source" "$archive/old/$key" || return 1
  fi
}

create_old_archive() {
  archive=$1
  scope=$2
  stamp=$(basename -- "$archive")
  mkdir -p "$archive/old" "$archive/resolved" || return 1

  {
    printf 'created_at=%s\n' "$stamp"
    printf 'repository=%s\n' "$REPOSITORY_URL"
    printf 'package_version=%s\n' "$PACKAGE_VERSION"
    printf 'scope=%s\n' "$scope"
    printf 'fluidd_root=%s\n' "$FLUIDD_ROOT"
    printf 'klipper_root=%s\n' "$KLIPPER_ROOT"
    printf 'moonraker_root=%s\n' "$MOONRAKER_ROOT"
    printf 'acepro_root=%s\n' "$ACEPRO_ROOT"
    printf 'printer_config_dir=%s\n' "$PRINTER_CONFIG_DIR"
  } > "$archive/manifest.txt" || return 1

  case "$scope" in
    all|driver)
      if path_exists "$TARGET_CONFIG_LINK"; then
        cp -L "$TARGET_CONFIG_LINK" "$archive/resolved/current-ace.cfg" || return 1
      elif path_exists "$TARGET_CONFIG_ROOT"; then
        cp -L "$TARGET_CONFIG_ROOT" "$archive/resolved/current-ace.cfg" || return 1
      fi
      ;;
  esac

  case "$scope" in
    all|card)
      archive_item "$archive" fluidd "$FLUIDD_ROOT" || return 1
      archive_item "$archive" moonraker/ace_status.py "$TARGET_COMPONENT" || return 1
      archive_item "$archive" moonraker/moonraker.conf "$MOONRAKER_CONF" || return 1
      archive_item "$archive" ace-web "$TARGET_WEB" || return 1
      ;;
  esac
  case "$scope" in
    all|driver)
      archive_item "$archive" klipper-driver/ace.py "$TARGET_DRIVER_LINK" || return 1
      archive_item "$archive" ace-root-driver/ace.py "$TARGET_DRIVER_ROOT" || return 1
      archive_item "$archive" printer-config/ace.cfg "$TARGET_CONFIG_LINK" || return 1
      archive_item "$archive" ace-root-config/ace.cfg "$TARGET_CONFIG_ROOT" || return 1
      archive_item "$archive" ace-root-config/ace.cfg.example "$ACEPRO_ROOT/ace.cfg.example" || return 1
      archive_item "$archive" ace-root-config/requirements.txt "$ACEPRO_ROOT/requirements.txt" || return 1
      archive_item "$archive" printer-config/printer.cfg "$PRINTER_CFG" || return 1
      ;;
  esac
  archive_item "$archive" state/installed "$MARKER" || return 1
  : > "$archive/archive.complete" || return 1
}

archive_scope() {
  sed -n 's/^scope=//p' "$1/manifest.txt" | tail -n 1
}

baseline_file() {
  case "$1" in
    all) printf '%s\n' "$BASELINE_FILE" ;;
    driver) printf '%s\n' "$DRIVER_BASELINE_FILE" ;;
    card) printf '%s\n' "$CARD_BASELINE_FILE" ;;
    *) return 1 ;;
  esac
}

restore_item() {
  archive=$1
  quarantine=$2
  key=$3
  target=$4
  marker="$archive/present.$(printf '%s' "$key" | tr '/' '_')"
  if [ ! -f "$archive/archive.complete" ] && [ ! -f "$marker" ]; then
    return 0
  fi
  if path_exists "$target"; then
    mkdir -p "$quarantine/$(dirname -- "$key")" || return 1
    mv "$target" "$quarantine/$key" || return 1
  fi
  if [ -f "$marker" ]; then
    mkdir -p "$(dirname -- "$target")" || return 1
    cp -a "$archive/old/$key" "$target" || return 1
  fi
}

restore_archive() {
  archive=$1
  quarantine=${2:-"$archive/restore-quarantine-$(date +%Y%m%d-%H%M%S)-$$"}
  scope=$(archive_scope "$archive")
  [ -n "$scope" ] || scope=all
  mkdir -p "$quarantine" || return 1
  warn "正在从 old 归档恢复: $archive"

  case "$scope" in
    all|card)
      restore_item "$archive" "$quarantine" fluidd "$FLUIDD_ROOT" || return 1
      restore_item "$archive" "$quarantine" moonraker/ace_status.py "$TARGET_COMPONENT" || return 1
      restore_item "$archive" "$quarantine" moonraker/moonraker.conf "$MOONRAKER_CONF" || return 1
      restore_item "$archive" "$quarantine" ace-web "$TARGET_WEB" || return 1
      fix_fluidd_permissions "$FLUIDD_ROOT" || return 1
      ;;
  esac
  case "$scope" in
    all|driver)
      restore_item "$archive" "$quarantine" ace-root-driver/ace.py "$TARGET_DRIVER_ROOT" || return 1
      restore_item "$archive" "$quarantine" klipper-driver/ace.py "$TARGET_DRIVER_LINK" || return 1
      restore_item "$archive" "$quarantine" ace-root-config/ace.cfg "$TARGET_CONFIG_ROOT" || return 1
      restore_item "$archive" "$quarantine" ace-root-config/ace.cfg.example "$ACEPRO_ROOT/ace.cfg.example" || return 1
      restore_item "$archive" "$quarantine" ace-root-config/requirements.txt "$ACEPRO_ROOT/requirements.txt" || return 1
      restore_item "$archive" "$quarantine" printer-config/ace.cfg "$TARGET_CONFIG_LINK" || return 1
      restore_item "$archive" "$quarantine" printer-config/printer.cfg "$PRINTER_CFG" || return 1
      ;;
  esac
  restore_item "$archive" "$quarantine" state/installed "$MARKER" || return 1
}

append_moonraker_config() {
  if ! grep -Eq '^[[:space:]]*\[ace_status\][[:space:]]*$' "$MOONRAKER_CONF"; then
    {
      printf '\n# Added by %s %s\n' "$APP_NAME" "$PACKAGE_VERSION"
      printf '[ace_status]\n'
      printf 'upper_sensor_name: extruder_sensor\n'
      printf 'lower_sensor_name: toolhead_sensor\n'
    } >> "$MOONRAKER_CONF" || return 1
  fi
}

append_printer_include() {
  if ! grep -Eq '^[[:space:]]*\[include[[:space:]]+ace\.cfg\][[:space:]]*$' "$PRINTER_CFG"; then
    {
      printf '\n# Added by %s %s\n' "$APP_NAME" "$PACKAGE_VERSION"
      printf '[include ace.cfg]\n'
    } >> "$PRINTER_CFG" || return 1
  fi
}

install_dependencies() {
  [ "${ACEPROSV08_SKIP_DEPENDENCIES:-0}" = "1" ] && return 0
  if [ -x "$KLIPPER_PYTHON" ]; then
    if "$KLIPPER_PYTHON" -c 'import serial' >/dev/null 2>&1; then
      ok "Klipper Python 已包含 pyserial"
    else
      warn "Klipper Python 缺少 pyserial，正在安装 pyserial 3.5"
      "$KLIPPER_PYTHON" -m pip install 'pyserial==3.5' || return 1
    fi
  else
    warn "未找到 $KLIPPER_PYTHON，请手动安装 pyserial 3.5"
  fi
}

install_driver_files() {
  archive=$1
  config_mode=$2
  mkdir -p "$ACEPRO_ROOT/extras" "$KLIPPER_ROOT/klippy/extras" "$PRINTER_CONFIG_DIR" || return 1

  cp -a "$PAYLOAD_DRIVER" "$TARGET_DRIVER_ROOT" || return 1
  ln -s "$TARGET_DRIVER_ROOT" "$TARGET_DRIVER_LINK" || return 1
  if [ "$config_mode" = "preserve" ] && [ -f "$archive/resolved/current-ace.cfg" ]; then
    cp -a "$archive/resolved/current-ace.cfg" "$TARGET_CONFIG_ROOT" || return 1
  else
    cp -a "$PAYLOAD_CONFIG" "$TARGET_CONFIG_ROOT" || return 1
  fi
  cp -a "$PAYLOAD_CONFIG" "$ACEPRO_ROOT/ace.cfg.example" || return 1
  ln -s "$TARGET_CONFIG_ROOT" "$TARGET_CONFIG_LINK" || return 1
  cp -a "$PAYLOAD_REQUIREMENTS" "$ACEPRO_ROOT/requirements.txt" || return 1
  cp -a "$archive/old/printer-config/printer.cfg" "$PRINTER_CFG" || return 1
  append_printer_include || return 1
  install_dependencies || return 1
}

install_card_files() {
  archive=$1
  target_parent=$(dirname -- "$FLUIDD_ROOT")
  target_name=$(basename -- "$FLUIDD_ROOT")
  stage="$target_parent/.${target_name}.aceprosv08-stage-$$"
  mkdir -p "$ACEPRO_ROOT/ace_status_integration" "$MOONRAKER_ROOT/moonraker/components" || return 1

  cp -a "$PAYLOAD_FLUIDD" "$stage" || return 1
  if [ -f "$archive/old/fluidd/config.json" ]; then
    cp -a "$archive/old/fluidd/config.json" "$stage/config.json" || return 1
  fi
  cp -a "$PAYLOAD_WEB/." "$stage/" || return 1
  mv "$stage" "$FLUIDD_ROOT" || return 1
  fix_fluidd_permissions "$FLUIDD_ROOT" || return 1
  cp -a "$PAYLOAD_MOONRAKER" "$TARGET_COMPONENT" || return 1
  cp -a "$PAYLOAD_WEB" "$TARGET_WEB" || return 1
  cp -a "$archive/old/moonraker/moonraker.conf" "$MOONRAKER_CONF" || return 1
  append_moonraker_config || return 1
}

install_files() {
  archive=$1
  scope=$2
  config_mode=$3
  case "$scope" in
    all|driver) install_driver_files "$archive" "$config_mode" || return 1 ;;
  esac
  case "$scope" in
    all|card) install_card_files "$archive" || return 1 ;;
  esac

  mkdir -p "$STATE_DIR" || return 1
  baseline=$(baseline_file "$scope") || return 1
  if [ ! -s "$baseline" ]; then
    printf '%s\n' "$archive" > "$baseline" || return 1
  fi
  {
    printf 'installed_at=%s\n' "$(date +%Y%m%d-%H%M%S)"
    printf 'package_version=%s\n' "$PACKAGE_VERSION"
    printf 'scope=%s\n' "$scope"
    printf 'config_mode=%s\n' "$config_mode"
    printf 'source=%s\n' "$ROOT_DIR"
    printf 'old_archive=%s\n' "$archive"
  } > "$MARKER" || return 1
}

install_suite() {
  force=${1:-0}
  scope=${2:-all}
  config_mode=${3:-preserve}
  verify_payload || return 1
  compile_python_payload || return 1
  check_install_targets "$scope" || return 1
  case "$scope" in
    all|card)
      check_fluidd_compatibility || {
        warn "用户取消安装，未创建 old 归档，也未修改任何文件"
        return 1
      }
      ;;
  esac
  if [ "$force" = "1" ]; then
    warn "强制安装：跳过现有驱动/API 判断，但不会跳过校验、old 归档或失败恢复"
  else
    check_environment "$scope" || return 1
  fi

  archive="$OLD_ROOT/$(date +%Y%m%d-%H%M%S)-$$"
  if ! create_old_archive "$archive" "$scope"; then
    restore_archive "$archive" "$archive/archive-failure-quarantine" || bad "归档失败后的自动恢复未完成，请检查 $archive"
    bad "安装前 old 归档失败，未开始写入新文件"
    return 1
  fi
  ok "旧文件已移动到: $archive/old"

  if install_files "$archive" "$scope" "$config_mode"; then
    case "$scope" in
      all) ok "驱动、配置、Moonraker 适配层、Fluidd 卡片和独立页面安装完成" ;;
      driver) ok "ACEPROSV08 驱动和配置已安装，Fluidd 卡片保持不变" ;;
      card) ok "Fluidd 卡片、Moonraker 适配层和独立页面已安装，驱动保持不变" ;;
    esac
    [ "$scope" != "card" ] && [ "$config_mode" = "preserve" ] && ok "已保留原 ace.cfg；新版模板位于 $ACEPRO_ROOT/ace.cfg.example"
    ok "如有兼容问题，可运行 sh ui-installer.sh --rollback-latest 回滚本次安装"
    warn "安装器未自动重启服务。确认当前没有打印任务后，请重启 Klipper 和 Moonraker。"
  else
    restore_archive "$archive" "$archive/install-failure-quarantine" || bad "自动恢复失败，请保留 old 归档并人工检查"
    bad "安装失败，已尝试恢复安装前状态"
    return 1
  fi
}

rollback_latest() {
  [ -s "$MARKER" ] || { bad "没有找到当前安装记录"; return 1; }
  previous=$(sed -n 's/^old_archive=//p' "$MARKER" | tail -n 1)
  [ -n "$previous" ] || { bad "安装记录中没有上一次 old 归档路径"; return 1; }
  scope=$(sed -n 's/^scope=//p' "$MARKER" | tail -n 1)
  [ -n "$scope" ] || scope=$(archive_scope "$previous")
  case "$scope" in all|driver|card) ;; *) bad "安装记录中的范围无效: $scope"; return 1 ;; esac
  [ -f "$previous/archive.complete" ] || { bad "上一次 old 归档不完整或不存在: $previous"; return 1; }

  current="$OLD_ROOT/$(date +%Y%m%d-%H%M%S)-$$"
  if ! create_old_archive "$current" "$scope"; then
    restore_archive "$current" "$current/archive-failure-quarantine" || bad "回滚前归档失败后的自动恢复未完成"
    bad "回滚前无法归档当前版本，已取消回滚"
    return 1
  fi
  ok "当前版本已移动到: $current/old"
  if restore_archive "$previous" "$current/rollback-quarantine"; then
    ok "已回滚到上一次安装前状态: $previous"
    warn "确认没有打印任务后，请重启 Klipper 和 Moonraker。"
  else
    bad "回滚失败，正在尝试恢复回滚前版本"
    restore_archive "$current" "$current/rollback-failure-quarantine" || bad "自动恢复失败，请人工检查 $current"
    return 1
  fi
}

uninstall_suite() {
  scope=${1:-all}
  baseline_file_path=$(baseline_file "$scope") || return 1
  [ -s "$baseline_file_path" ] || { bad "没有找到 $scope 范围的首次安装前 old 归档记录"; return 1; }
  baseline=$(cat "$baseline_file_path")
  [ -d "$baseline/old" ] || { bad "首次安装归档不存在: $baseline"; return 1; }
  archive="$OLD_ROOT/$(date +%Y%m%d-%H%M%S)-$$"
  if ! create_old_archive "$archive" "$scope"; then
    restore_archive "$archive" "$archive/archive-failure-quarantine" || bad "归档失败后的自动恢复未完成，请检查 $archive"
    bad "卸载前归档失败，已取消卸载"
    return 1
  fi
  ok "卸载前当前文件已移动到: $archive/old"
  restore_archive "$baseline" "$archive/uninstall-quarantine" || {
    bad "恢复首次安装前状态失败，当前文件保留在卸载归档中"
    return 1
  }
  if [ -f "$MARKER" ]; then
    mv "$MARKER" "$STATE_DIR/installed.uninstalled.$(date +%Y%m%d-%H%M%S)"
  fi
  ok "已恢复 $scope 范围首次安装前的文件"
}

show_status() {
  header
  printf 'Fluidd 目录       : %s\n' "$FLUIDD_ROOT"
  printf 'Klipper 驱动      : %s\n' "$TARGET_DRIVER_LINK"
  printf 'ACEPROSV08 目录   : %s\n' "$ACEPRO_ROOT"
  printf 'ACE 配置          : %s\n' "$TARGET_CONFIG_LINK"
  printf 'Moonraker 配置    : %s\n' "$MOONRAKER_CONF"
  printf 'old 归档目录      : %s\n' "$OLD_ROOT"
}

menu() {
  while true; do
    header
    printf '%s\n' '|  1. 安装 / 更新整套组件（默认：驱动 + 卡片，保留 ace.cfg）        |'
    printf '%s\n' '|  2. 仅安装 / 更新 ACEPROSV08 驱动和配置                           |'
    printf '%s\n' '|  3. 仅安装 / 更新 Fluidd 卡片和 Moonraker 适配层                  |'
    printf '%s\n' '|  4. 整套安装并使用新版 ace.cfg 模板                               |'
    printf '%s\n' '|  5. 强制整套安装（跳过现有驱动/API 判断）                          |'
    printf '%s\n' '|  6. 回滚到上一次安装前版本                                        |'
    printf '%s\n' '|  7. 卸载并恢复首次安装前版本                                      |'
    printf '%s\n' '|  8. 检查安装状态                                                  |'
    printf '%s\n' '|  9. 退出                                                          |'
    line
    printf '请选择 [1-9]: '
    IFS= read -r choice || exit 0
    case "$choice" in
      1) confirm '确认安装 / 更新整套组件？旧文件会移动到 old 目录。' && install_suite 0 all preserve || true; pause_menu ;;
      2) confirm '确认仅安装 / 更新驱动？Fluidd 卡片不会改动。' && install_suite 0 driver preserve || true; pause_menu ;;
      3) confirm '确认仅安装 / 更新卡片？ACEPROSV08 驱动不会改动。' && install_suite 0 card preserve || true; pause_menu ;;
      4) confirm '确认使用新版 ace.cfg 模板安装整套组件？原配置会保存在 old 目录。' && install_suite 0 all replace || true; pause_menu ;;
      5) confirm '确认强制安装整套组件？仍会先校验文件并创建 old 归档。' && install_suite 1 all preserve || true; pause_menu ;;
      6) confirm '确认回滚最近一次安装？当前版本也会先进入 old 归档。' && rollback_latest || true; pause_menu ;;
      7) confirm '确认卸载并恢复首次安装前版本？' && uninstall_suite all || true; pause_menu ;;
      8) show_status; pause_menu ;;
      9) exit 0 ;;
      *) bad "无效选项: $choice"; pause_menu ;;
    esac
  done
}

YES=0
if [ "${1:-}" = "--yes" ]; then YES=1; shift; fi

case "${1:-}" in
  --install) install_suite 0 all preserve ;;
  --install-driver) install_suite 0 driver preserve ;;
  --install-card) install_suite 0 card preserve ;;
  --install-new-config) install_suite 0 all replace ;;
  --install-force) install_suite 1 all preserve ;;
  --rollback-latest) rollback_latest ;;
  --uninstall) uninstall_suite all ;;
  --uninstall-driver) uninstall_suite driver ;;
  --uninstall-card) uninstall_suite card ;;
  --status) show_status ;;
  --help|-h)
    printf '%s\n' "用法: sh ui-installer.sh [--install|--install-driver|--install-card|--install-new-config|--install-force|--rollback-latest|--uninstall|--uninstall-driver|--uninstall-card|--status]"
    ;;
  '') menu ;;
  *) bad "未知参数: $1"; exit 2 ;;
esac
