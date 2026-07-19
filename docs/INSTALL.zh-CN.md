# ACEPROSV08 一体化安装、升级与恢复教程

## 1. 适用范围

本套件仅适配一台 ACE Pro、四料槽和 `szkrisz/ACEPROSV08`。若配置中仍包含 Kobra-S1 专用字段或旧驱动 include，请先停止并清理冲突，不能同时加载两套 `[ace]`。

安装器会同时处理：

- `~/ACEPROSV08/extras/ace.py`
- `~/klipper/klippy/extras/ace.py` 软链接
- `~/ACEPROSV08/ace.cfg` 与 `~/printer_data/config/ace.cfg` 软链接
- Moonraker `ace_status.py` 与 `[ace_status]`
- Fluidd 完整构建产物和 `/ace.html`

## 2. 安装前准备

1. 停止正在进行的打印，确认工具头和 ACE 没有执行送料、回抽或切刀。
2. 确认磁盘空间足够同时保存一份旧 Fluidd 和一份新 Fluidd。
3. 记录上方传感器、下方传感器和 ACE 串口的实际名称。
4. 如果机器已经能正常换料，优先选择“保留现有 ace.cfg”。

可选检查：

```bash
ls -l /dev/serial/by-id/
grep -n "include.*ace" ~/printer_data/config/printer.cfg
grep -Rni "^\[ace\]" ~/printer_data/config
```

## 3. Git 下载

```bash
cd ~
git clone --depth 1 https://github.com/Luomo520/fluidd-acepro-card-ACEPROSV08.git
cd fluidd-acepro-card-ACEPROSV08
```

如果目录已经存在：

```bash
cd ~/fluidd-acepro-card-ACEPROSV08
git pull --ff-only
```

## 4. 运行字符安装器

```bash
sh install.sh
```

安装范围：

- `1`：默认整套安装，同时更新驱动、配置、Moonraker 和 Fluidd 卡片，并保留现有 `ace.cfg`。
- `2`：仅更新 ACEPROSV08 驱动和配置，不修改 Fluidd 与 Moonraker。
- `3`：仅更新 Fluidd 卡片、Moonraker 适配层和独立页面，不修改 Klipper 驱动与 `ace.cfg`。
- `4`：整套安装并使用包内模板替换 `ace.cfg`，适合全新标定。
- `5`：环境检测误判时强制整套安装，仍然执行校验、归档和恢复保护。

整套安装和仅卡片安装会把当前 Fluidd 与本包测试版本 `v1.37.2` 比较：低版本会提示升级风险，高版本会提示降级风险，无法识别版本也会要求确认。取消后不会移动或修改目标文件。仅驱动模式不会读取或替换 Fluidd，因此不显示此提示。

命令行方式：

```bash
sh ui-installer.sh --yes --install
sh ui-installer.sh --yes --install-driver
sh ui-installer.sh --yes --install-card
sh ui-installer.sh --yes --install-new-config
sh ui-installer.sh --yes --install-force
sh ui-installer.sh --yes --rollback-latest
```

## 5. old 归档规则

实际写入前，旧文件会移动到：

```text
~/.local/share/aceprosv08-ui/old/YYYYMMDD-HHMMSS-PID/old/
```

目录按实际安装范围包含 `fluidd/`、`klipper-driver/`、`ace-root-driver/`、`printer-config/`、`moonraker/` 或 `ace-web/`。`manifest.txt` 的 `scope` 为 `all`、`driver` 或 `card`，`archive.complete` 表示归档完整。

安装失败时，新文件会移动到 `install-failure-quarantine/`，旧文件从同一归档恢复。安装器不使用 `rm -rf` 清理用户文件。

## 6. 配置策略

### 保留现有配置

安装器先解析当前 `~/printer_data/config/ace.cfg` 的实际内容，再移动旧软链接和旧驱动。随后它重建 `~/ACEPROSV08/ace.cfg` 与软链接，并把新版模板放到：

```bash
~/ACEPROSV08/ace.cfg.example
```

### 使用新版模板

选择菜单 `4` 后，原配置仍保存在 `old/`，但运行配置会替换为模板。必须在重启 Klipper 前填写：串口、上下传感器针脚、全部路径长度和切刀坐标。

## 7. 重启前检查

```bash
nano ~/printer_data/config/ace.cfg
```

重点检查：

- `serial`
- `extruder_sensor_pin`
- `toolhead_sensor_pin`
- `toolchange_load_length`
- `toolchange_retract_length`
- `bowden_tube_length`
- `toolhead_sensor_to_nozzle`
- `[gcode_macro CUT_TIP]` 内的 X/Y 坐标
- `_ACE_PRE_TOOLCHANGE` 的停靠位置是否适合本机

同时确认 `printer.cfg` 只有一个有效的：

```ini
[include ace.cfg]
```

Moonraker 默认追加：

```ini
[ace_status]
upper_sensor_name: extruder_sensor
lower_sensor_name: toolhead_sensor
```

这里填写 Klipper 传感器对象名，不是 MCU 引脚名。

## 8. 安全重启

确认没有打印任务后：

```bash
sudo systemctl restart klipper
sudo systemctl restart moonraker
```

检查：

```text
http://打印机IP/
http://打印机IP/ace.html
http://打印机IP:7125/server/ace/status
```

若 Fluidd 仍显示旧页面，请强制刷新浏览器或清除该站点的 Service Worker 缓存。

## 9. 首次动作测试顺序

安装器不会自动移动硬件。建议人工按以下顺序验证：

1. 只读检查 ACE 在线状态和四槽库存。
2. 手动按压上、下传感器，确认界面开关状态对应正确。
3. 在无打印任务时短距离测试送料/回抽。
4. 空载检查切刀坐标，不带耗材确认不会撞机。
5. 最后进行一次完整 `T0 -> T1` 换料并观察各阶段提示。

## 10. 卸载与恢复

```bash
cd ~/fluidd-acepro-card-ACEPROSV08
sh uninstall.sh
```

卸载前会把当前版本再次移动到新的 `old/` 目录，然后复制恢复首次安装前的驱动、配置、Fluidd 和 Moonraker 文件。完成后仍需在无打印任务时重启 Klipper 与 Moonraker。

如果只是本次更新后出现兼容问题，先使用最近一次回滚：

```bash
sh ui-installer.sh --rollback-latest
```

该操作会先把当前版本归档，再恢复最近一次安装前的 Fluidd、驱动、配置和 Moonraker 文件。它不等同于卸载；卸载始终恢复首次安装前基线。

独立范围卸载：

```bash
sh ui-installer.sh --uninstall-driver
sh ui-installer.sh --uninstall-card
```

## 11. 常见问题

- Fluidd 空白：检查 `~/fluidd` 文件权限和浏览器 Service Worker；安装器会执行 `chmod -R a+rX`。
- `[ace_status]` 未解析：确认 `~/moonraker/moonraker/components/ace_status.py` 存在并重启 Moonraker。
- API 404：确认 Moonraker 已重启，且访问端口为 `7125`。
- 驱动加载失败：先看 `klippy.log`，通常是串口、传感器针脚、重复 `[ace]` 或重复宏配置。
- 换料走向错误：立即暂停，核对上/下传感器定义和 `toolchange_*` 距离，不要用更大距离掩盖路径配置错误。
