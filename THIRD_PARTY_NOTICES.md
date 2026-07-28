# 第三方来源声明

本项目以 GPL-3.0 发布，并保留上游项目的许可义务和来源说明。

## szkrisz/ACEPROSV08

- 仓库：https://github.com/szkrisz/ACEPROSV08
- 许可证：GPL-3.0
- 用途：本项目 Klipper 驱动、ACE 串口协议、G-code 命令和配置结构的上游基础。
- 本项目修改范围：在保留 GPL-3.0 来源的前提下形成独立的 Ace Pro Control Center 驱动，并增加状态模型、断联保护、标定、自动烘干、Moonraker API、Fluidd UI、中文辅助页面和事务式安装器。

## Kobra-S1/ACEPRO

- 仓库：https://github.com/Kobra-S1/ACEPRO
- 许可证：GPL-3.0
- 用途：参考 ACE Pro 网页端交互、中文页面迁移基础、料卷 SVG 视觉样式。
- 本项目修改范围：移除多设备假设，改为 Ace Pro Control Center 单设备 API 和 `INDEX` 指令。

## fluidd-core/fluidd

- 仓库：https://github.com/fluidd-core/fluidd
- 文档：https://docs.fluidd.xyz/
- 许可证：GPL-3.0
- 用途：Fluidd 仪表盘源码、布局、构建产物和小组件接入方式。
- 本项目修改范围：增加 ACE Pro 卡片、页面入口、中文文案和相关构建产物。

## Moonraker

- 仓库：https://github.com/Arksine/moonraker
- 许可证：GPL-3.0
- 用途：Fluidd 与 Klipper 之间的 HTTP / WebSocket 服务端接口和组件加载机制。
- 本项目修改范围：新增独立的 `ace_status` Moonraker 组件，仅暴露 Ace Pro Control Center 状态和经过白名单校验的控制命令；未修改 Moonraker 上游源码。

## Vue

- 仓库：https://github.com/vuejs/core
- 许可证：MIT
- 用途：独立控制页面运行时。
- 许可证全文：[`licenses/Vue-MIT.txt`](licenses/Vue-MIT.txt)

## 责任说明

本项目不是 Anycubic、Fluidd、Moonraker 或上游驱动作者的官方项目。安装器不负责识别或迁移其他 ACE 驱动；安装前请备份打印机配置，并确认不会同时加载多套 `[ace]` 驱动。
