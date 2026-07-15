# ACEPROSV08 Fluidd 卡片安装教程

## 1. 前提

请先确认打印机已经安装 `szkrisz/ACEPROSV08` 驱动，并且 Klipper/Moonraker/Fluidd 可以正常启动。

本项目不适配 `Kobra-S1/ACEPRO`。如果机器上仍有 Kobra-S1 驱动，请先卸载后再安装 ACEPROSV08。

## 2. 下载

```bash
cd ~
git clone --depth 1 https://github.com/Luomo520/fluidd-acepro-card-ACEPROSV08.git
cd fluidd-acepro-card-ACEPROSV08
```

## 3. 运行安装器

```bash
sh ui-installer.sh
```

普通安装会检测：

- ACEPROSV08 驱动目录。
- Moonraker 基础 API。
- Fluidd 目录。
- 本仓库内置文件完整性。

强制安装：

```bash
sh ui-installer.sh --install-force
```

强制安装只跳过驱动/API 检测，不跳过备份。

字符菜单中的“检查安装状态”会显示 Fluidd 版本、ACEPROSV08 驱动状态、面板版本、API 状态和最近备份。

## 4. 重启服务

安装器会复制 Moonraker 组件并向 `moonraker.conf` 追加 `[ace_status]`。安装完成后请重启 Moonraker：

```bash
sudo systemctl restart moonraker
```

如果 Fluidd 页面仍显示旧界面，请强制刷新浏览器，或清除当前站点缓存和 Service Worker。

## 5. 访问

- Fluidd 主页面：`http://打印机IP/`
- 独立页面：`http://打印机IP/ace.html`
- API 测试：`http://打印机IP:7125/server/ace/status`

Fluidd 卡片与独立页面提供同一组核心能力：上下传感器状态、烘干、四料槽库存、装卸与换卷、助推、手动送料/回抽、无限续料和传感器诊断。第一版不支持多台 ACE Pro。

## 6. 卸载

```bash
cd ~/fluidd-acepro-card-ACEPROSV08
sh ui-installer.sh --uninstall
```

卸载前会再次备份当前状态，然后恢复首次安装前的 Fluidd、Moonraker 配置、Moonraker 组件和 ACE 独立网页。首次安装前不存在的文件会移入卸载备份，不会直接删除。

## 7. 备份位置

```bash
~/.local/share/aceprosv08-ui/backups/
```

不要手动删除该目录，除非你已经确认不需要一键恢复。

## 8. 传感器名称

默认配置为：

```ini
[ace_status]
upper_sensor_name: extruder_sensor
lower_sensor_name: toolhead_sensor
```

如果你的 Klipper 对象名称不同，请修改这两个值并重启 Moonraker。这里填写的是对象名，不是 MCU 引脚名。
