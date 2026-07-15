# 第三方来源声明

本项目以 GPL-3.0 发布，并保留上游项目的许可义务和来源说明。

## szkrisz/ACEPROSV08

- 仓库：https://github.com/szkrisz/ACEPROSV08
- 许可证：GPL-3.0
- 用途：ACEPROSV08 Klipper 驱动、ACE G-code 命令、配置结构。
- 本项目修改范围：增加只读状态字段，新增 Moonraker API、Fluidd UI、中文独立页面和安装器。

## Kobra-S1/ACEPRO

- 仓库：https://github.com/Kobra-S1/ACEPRO
- 许可证：GPL-3.0
- 用途：参考 ACE Pro 网页端交互、中文页面迁移基础、料卷 SVG 视觉样式。
- 本项目修改范围：移除多设备假设，改为 ACEPROSV08 单设备 API 和 `INDEX` 指令。

## fluidd-core/fluidd

- 仓库：https://github.com/fluidd-core/fluidd
- 文档：https://docs.fluidd.xyz/
- 许可证：GPL-3.0
- 用途：Fluidd 仪表盘源码、布局、构建产物和小组件接入方式。
- 本项目修改范围：增加 ACE Pro 卡片、页面入口、中文文案和相关构建产物。

## Vue

- 仓库：https://github.com/vuejs/core
- 许可证：MIT
- 用途：独立控制页面运行时。

## 责任说明

本项目不是 Anycubic、Fluidd 或 Moonraker 官方项目。安装前请备份打印机配置，并确认当前机器安装的是 `szkrisz/ACEPROSV08` 驱动。
