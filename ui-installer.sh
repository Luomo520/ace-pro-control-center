#!/usr/bin/env sh
set -eu

APP_NAME="ACEPROSV08 Fluidd UI"
PANEL_VERSION="0.1.0"
REPOSITORY_URL="https://github.com/Luomo520/fluidd-acepro-card-ACEPROSV08"

ROOT_DIR=$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)
FLUIDD_ROOT=${FLUIDD_ROOT:-"$HOME/fluidd"}
MOONRAKER_ROOT=${MOONRAKER_ROOT:-"$HOME/moonraker"}
MOONRAKER_CONF=${MOONRAKER_CONF:-"$HOME/printer_data/config/moonraker.conf"}
ACEPRO_ROOT=${ACEPRO_ROOT:-"$HOME/ACEPROSV08"}
STATE_DIR=${ACEPROSV08_UI_STATE_DIR:-"$HOME/.local/share/aceprosv08-ui"}
BACKUP_ROOT="$STATE_DIR/backups"
BASELINE_FILE="$STATE_DIR/first_install_backup"
MARKER="$STATE_DIR/installed"

PAYLOAD_FLUIDD="$ROOT_DIR/fluidd-dist"
PAYLOAD_MOONRAKER="$ROOT_DIR/ace_status_integration/moonraker/ace_status.py"
PAYLOAD_WEB="$ROOT_DIR/ace_status_integration/web"

ok() { printf '[  OK  ] %s\n' "$1"; }
warn() { printf '[ 警告 ] %s\n' "$1" >&2; }
bad() { printf '[ 失败 ] %s\n' "$1" >&2; }
line() { printf '%s\n' '+----------------------------------------------------------------+'; }

first_line() {
  if [ -s "$1" ]; then
    IFS= read -r value < "$1" || true
    printf '%s\n' "${value:-未知}"
  else
    printf '%s\n' '未知'
  fi
}

detect_fluidd_version() {
  first_line "$FLUIDD_ROOT/.version"
}

detect_driver_version() {
  if [ -d "$ACEPRO_ROOT/.git" ] && command -v git >/dev/null 2>&1; then
    git -C "$ACEPRO_ROOT" describe --tags --always --dirty 2>/dev/null || printf '%s\n' '已安装'
  elif [ -d "$ACEPRO_ROOT" ]; then
    printf '%s\n' '已安装'
  else
    printf '%s\n' '未安装'
  fi
}

detect_api_status() {
  if command -v curl >/dev/null 2>&1; then
    code=$(curl -sS -o /dev/null -w '%{http_code}' --max-time 5 http://127.0.0.1:7125/server/ace/status 2>/dev/null || true)
    [ "$code" = "200" ] && printf '%s\n' '可访问' || printf '不可访问(%s)\n' "${code:-无响应}"
  else
    printf '%s\n' '未检测：缺少 curl'
  fi
}

latest_backup() {
  if [ -d "$BACKUP_ROOT" ]; then
    find "$BACKUP_ROOT" -maxdepth 1 -type d -name '20*' 2>/dev/null | sort | tail -n 1 | sed 's#^.*/##'
  fi
}

detect_install_state() {
  [ -f "$MARKER" ] && printf '%s\n' '已安装' || printf '%s\n' '未安装'
}

header() {
  command -v clear >/dev/null 2>&1 && clear || true
  line
  printf '| %-62s |\n' "$APP_NAME"
  line
  printf '  Fluidd 版本       : %s\n' "$(detect_fluidd_version)"
  printf '  ACEPROSV08 驱动   : %s\n' "$(detect_driver_version)"
  printf '  面板版本          : %s\n' "$PANEL_VERSION"
  printf '  API 状态          : %s\n' "$(detect_api_status)"
  printf '  安装状态          : %s\n' "$(detect_install_state)"
  printf '  最近备份          : %s\n' "$(latest_backup || printf '无')"
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
  case "$answer" in
    y|Y|yes|YES) return 0 ;;
    *) return 1 ;;
  esac
}

require_file() {
  [ -f "$1" ] || { bad "缺少文件: $1"; return 1; }
}

require_dir() {
  [ -d "$1" ] || { bad "缺少目录: $1"; return 1; }
}

verify_payload() {
  require_dir "$PAYLOAD_FLUIDD"
  require_file "$PAYLOAD_FLUIDD/index.html"
  require_file "$PAYLOAD_MOONRAKER"
  require_file "$PAYLOAD_WEB/ace.html"
  require_file "$PAYLOAD_WEB/ace-dashboard.js"
  require_file "$PAYLOAD_WEB/ace-dashboard.css"
  if command -v sha256sum >/dev/null 2>&1 && [ -f "$ROOT_DIR/manifest.sha256" ]; then
    (cd "$ROOT_DIR" && sha256sum -c manifest.sha256 >/dev/null) || {
      bad "安装文件校验失败，请重新通过 Git 下载仓库"
      return 1
    }
  else
    warn "系统缺少 sha256sum 或校验清单，已执行基础文件检查"
  fi
}

check_install_targets() {
  require_dir "$FLUIDD_ROOT"
  require_file "$FLUIDD_ROOT/index.html"
  require_dir "$MOONRAKER_ROOT/moonraker/components"
  require_file "$MOONRAKER_CONF"
  require_dir "$ACEPRO_ROOT"
}

check_driver() {
  failed=0
  [ -f "$ACEPRO_ROOT/extras/ace.py" ] || [ -f "$HOME/klipper/klippy/extras/ace.py" ] || {
    bad "未检测到 ACEPROSV08 驱动文件。默认目录: $ACEPRO_ROOT"
    failed=1
  }
  if command -v curl >/dev/null 2>&1; then
    code=$(curl -sS -o /dev/null -w '%{http_code}' --max-time 5 http://127.0.0.1:7125/server/info 2>/dev/null || true)
    [ "$code" = "200" ] || { bad "Moonraker API 不可访问: HTTP $code"; failed=1; }
  else
    warn "系统缺少 curl，跳过 Moonraker API 检测"
  fi
  [ "$failed" -eq 0 ]
}

create_backup() {
  stamp=$(date +%Y%m%d-%H%M%S)-$$
  backup="$BACKUP_ROOT/$stamp"
  mkdir -p "$backup" || return 1

  if [ -e "$FLUIDD_ROOT" ]; then
    : > "$backup/present.fluidd"
    cp -a "$FLUIDD_ROOT" "$backup/fluidd" || return 1
  fi
  if [ -f "$MOONRAKER_CONF" ]; then
    : > "$backup/present.moonraker_conf"
    cp -a "$MOONRAKER_CONF" "$backup/moonraker.conf" || return 1
  fi
  component="$MOONRAKER_ROOT/moonraker/components/ace_status.py"
  if [ -f "$component" ]; then
    : > "$backup/present.component"
    mkdir -p "$backup/moonraker_component" || return 1
    cp -a "$component" "$backup/moonraker_component/ace_status.py" || return 1
  fi
  if [ -d "$ACEPRO_ROOT/ace_status_integration/web" ]; then
    : > "$backup/present.ace_web"
    mkdir -p "$backup/ace_web" || return 1
    cp -a "$ACEPRO_ROOT/ace_status_integration/web" "$backup/ace_web/web" || return 1
  fi

  {
    printf 'created_at=%s\n' "$stamp"
    printf 'repository=%s\n' "$REPOSITORY_URL"
    printf 'panel_version=%s\n' "$PANEL_VERSION"
    printf 'fluidd_root=%s\n' "$FLUIDD_ROOT"
    printf 'moonraker_conf=%s\n' "$MOONRAKER_CONF"
    printf 'acepro_root=%s\n' "$ACEPRO_ROOT"
  } > "$backup/manifest.txt" || return 1

  [ -f "$backup/manifest.txt" ] || { bad "备份清单创建失败"; return 1; }
  printf '%s\n' "$backup"
}

restore_backup() {
  backup=$1
  quarantine=${2:-"$backup/restore-quarantine-$(date +%Y%m%d-%H%M%S)-$$"}
  mkdir -p "$quarantine" || return 1
  warn "正在从备份恢复: $backup"
  if [ -e "$FLUIDD_ROOT" ]; then
    mv "$FLUIDD_ROOT" "$quarantine/fluidd" || return 1
  fi
  if [ -f "$backup/present.fluidd" ]; then
    cp -a "$backup/fluidd" "$FLUIDD_ROOT" || return 1
  fi

  if [ -f "$MOONRAKER_CONF" ]; then
    mkdir -p "$quarantine/moonraker" || return 1
    mv "$MOONRAKER_CONF" "$quarantine/moonraker/moonraker.conf" || return 1
  fi
  if [ -f "$backup/present.moonraker_conf" ]; then
    mkdir -p "$(dirname -- "$MOONRAKER_CONF")" || return 1
    cp -a "$backup/moonraker.conf" "$MOONRAKER_CONF" || return 1
  fi

  component="$MOONRAKER_ROOT/moonraker/components/ace_status.py"
  if [ -f "$component" ]; then
    mkdir -p "$quarantine/moonraker_component" || return 1
    mv "$component" "$quarantine/moonraker_component/ace_status.py" || return 1
  fi
  if [ -f "$backup/present.component" ]; then
    mkdir -p "$MOONRAKER_ROOT/moonraker/components" || return 1
    cp -a "$backup/moonraker_component/ace_status.py" "$component" || return 1
  fi

  ace_web="$ACEPRO_ROOT/ace_status_integration/web"
  if [ -d "$ace_web" ]; then
    mkdir -p "$quarantine/ace_web" || return 1
    mv "$ace_web" "$quarantine/ace_web/web" || return 1
  fi
  if [ -f "$backup/present.ace_web" ]; then
    mkdir -p "$ACEPRO_ROOT/ace_status_integration" || return 1
    cp -a "$backup/ace_web/web" "$ace_web" || return 1
  fi
}

install_files() {
  backup=$1
  mkdir -p "$MOONRAKER_ROOT/moonraker/components" || return 1
  mkdir -p "$ACEPRO_ROOT/ace_status_integration/web" || return 1
  target_parent=$(dirname -- "$FLUIDD_ROOT")
  target_name=$(basename -- "$FLUIDD_ROOT")
  stage="$target_parent/.${target_name}.aceprosv08-stage-$$"

  [ ! -e "$stage" ] || { bad "暂存目录已存在: $stage"; return 1; }
  cp -a "$PAYLOAD_FLUIDD" "$stage" || return 1
  if [ -f "$FLUIDD_ROOT/config.json" ]; then
    cp -a "$FLUIDD_ROOT/config.json" "$stage/config.json" || return 1
  fi
  cp -a "$PAYLOAD_WEB/." "$stage/" || return 1

  if [ -e "$FLUIDD_ROOT" ]; then
    mv "$FLUIDD_ROOT" "$backup/replaced-fluidd" || return 1
  fi
  mv "$stage" "$FLUIDD_ROOT" || return 1

  cp -a "$PAYLOAD_MOONRAKER" "$MOONRAKER_ROOT/moonraker/components/ace_status.py" || return 1
  cp -a "$PAYLOAD_WEB/." "$ACEPRO_ROOT/ace_status_integration/web/" || return 1

  if [ -f "$MOONRAKER_CONF" ] && ! grep -Eq '^[[:space:]]*\[ace_status\][[:space:]]*$' "$MOONRAKER_CONF"; then
    {
      printf '\n# Added by %s %s\n' "$APP_NAME" "$PANEL_VERSION"
      printf '[ace_status]\n'
      printf 'upper_sensor_name: extruder_sensor\n'
      printf 'lower_sensor_name: toolhead_sensor\n'
    } >> "$MOONRAKER_CONF" || return 1
  fi

  mkdir -p "$STATE_DIR" || return 1
  if [ ! -s "$BASELINE_FILE" ]; then
    printf '%s\n' "$backup" > "$BASELINE_FILE" || return 1
  fi
  {
    printf 'installed_at=%s\n' "$(date +%Y%m%d-%H%M%S)"
    printf 'panel_version=%s\n' "$PANEL_VERSION"
    printf 'source=%s\n' "$ROOT_DIR"
  } > "$MARKER" || return 1
}

install_ui() {
  force=${1:-0}
  verify_payload || return 1
  check_install_targets || return 1
  if [ "$force" != "1" ]; then
    check_driver || return 1
  else
    warn "强制安装：已跳过驱动和 API 检测，但仍会执行备份和文件校验"
  fi
  backup=$(create_backup) || { bad "安装前备份失败，未写入任何安装文件"; return 1; }
  ok "已创建备份: $backup"
  if install_files "$backup"; then
    ok "安装完成。请在确认后重启 Moonraker，使 [ace_status] 组件加载。"
  else
    restore_backup "$backup" "$backup/install-failure-quarantine" || bad "自动恢复失败，请保留备份并人工检查"
    bad "安装失败，已尝试恢复"
    return 1
  fi
}

uninstall_ui() {
  [ -s "$BASELINE_FILE" ] || { bad "没有找到首次安装前备份记录"; return 1; }
  baseline=$(cat "$BASELINE_FILE")
  [ -d "$baseline" ] || { bad "备份目录不存在: $baseline"; return 1; }
  backup=$(create_backup) || { bad "卸载前备份失败，已取消卸载"; return 1; }
  ok "卸载前已创建备份: $backup"
  restore_backup "$baseline" "$backup/uninstall-quarantine" || {
    bad "恢复首次安装备份失败，当前文件已保留在卸载备份中"
    return 1
  }
  mv "$MARKER" "$STATE_DIR/installed.uninstalled.$(date +%Y%m%d-%H%M%S)" 2>/dev/null || true
  ok "已恢复首次安装前状态"
}

show_status() {
  header
  printf 'Fluidd 目录       : %s\n' "$FLUIDD_ROOT"
  printf 'Moonraker 配置    : %s\n' "$MOONRAKER_CONF"
  printf 'ACEPROSV08 目录   : %s\n' "$ACEPRO_ROOT"
  printf '状态目录          : %s\n' "$STATE_DIR"
}

menu() {
  while true; do
    header
    printf '%s\n' '|  1. 安装 / 更新 ACE Pro 界面                                 |'
    printf '%s\n' '|  2. 强制安装（跳过驱动和 API 检测）                          |'
    printf '%s\n' '|  3. 卸载界面并恢复安装前版本                                 |'
    printf '%s\n' '|  4. 检查安装状态                                             |'
    printf '%s\n' '|  5. 退出                                                     |'
    line
    printf '请选择 [1-5]: '
    IFS= read -r choice || exit 0
    case "$choice" in
      1) confirm '确认安装 / 更新？安装前会自动备份。' && install_ui 0 || true; pause_menu ;;
      2) confirm '确认强制安装？安装前仍会自动备份。' && install_ui 1 || true; pause_menu ;;
      3) confirm '确认卸载并恢复首次安装前版本？' && uninstall_ui || true; pause_menu ;;
      4) show_status; pause_menu ;;
      5) exit 0 ;;
      *) bad "无效选项: $choice"; pause_menu ;;
    esac
  done
}

YES=0
if [ "${1:-}" = "--yes" ]; then
  YES=1
  shift
fi

case "${1:-}" in
  --install) install_ui 0 ;;
  --install-force) install_ui 1 ;;
  --uninstall) uninstall_ui ;;
  --status) show_status ;;
  --help|-h)
    printf '%s\n' "用法: sh ui-installer.sh [--install|--install-force|--uninstall|--status]"
    ;;
  '') menu ;;
  *) bad "未知参数: $1"; exit 2 ;;
esac
