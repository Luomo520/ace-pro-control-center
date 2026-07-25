# ACEPROSV08 + Fluidd 卡片 v1.0.0

v1.0.0 是首个稳定整合版本，面向使用 `szkrisz/ACEPROSV08` 的 DIY Klipper 打印机。它把增强版驱动、Moonraker 受控 API、Fluidd 原生卡片、中文辅助页面和可回滚安装器统一为一套发布包。

> 本版本只支持一台 ACE Pro 和四个料槽，不兼容同时加载 `Kobra-S1/ACEPRO` 驱动。安装前必须停止打印并备份配置。

## 主要特色

- ACE Pro 作为 Fluidd 原生导航页面和仪表盘卡片运行，不创建另一套打印机管理网站。
- 四料槽横向显示，支持颜色、材料、温度、装载、卸载、清空、换卷和库存保存。
- 显示上方与下方耗材传感器、ACE 连接、烘干、当前槽位和换料诊断状态。
- 默认连续长距离送料，取消每 50/100 mm 的固定停顿；保留断续兼容开关。
- 默认使用快速回抽段加慢速停放段，取消每 100 mm 的回抽停顿。
- 上方传感器触发后按动作预计时长等待 ACE 停止并恢复就绪，降低慢速动作误超时概率。
- 送料失败时暂停打印并报告 `TA -> TB`、失败阶段、传感器状态和耗材预计位置。
- 安装、更新、回滚和卸载前均创建 `old/` 归档；失败时自动恢复。
- 已完整测试 Fluidd `v1.37.2`，其他版本由安装器提示兼容风险后让用户决定是否继续。

## 安装

```bash
cd ~
git clone --branch v1.0.0 --depth 1 \
  https://github.com/Luomo520/fluidd-acepro-card-ACEPROSV08.git
cd fluidd-acepro-card-ACEPROSV08
sh install.sh
```

默认菜单选项 `1` 会安装驱动和卡片，同时保留当前 `ace.cfg`。也可选择仅驱动、仅卡片、替换配置模板、强制安装、最近版本回滚或恢复首次安装前状态。

安装器不会自动重启服务。确认打印机空闲并完成配置检查后，再手动重启 Klipper 和 Moonraker。

完整步骤、必填参数和故障排查见 [README](../README.md) 与 [中文安装教程](INSTALL.zh-CN.md)。

## 项目来源与许可

本项目基于或参考以下开源项目：

- [szkrisz/ACEPROSV08](https://github.com/szkrisz/ACEPROSV08)
- [Kobra-S1/ACEPRO](https://github.com/Kobra-S1/ACEPRO)
- [fluidd-core/fluidd](https://github.com/fluidd-core/fluidd)
- [Arksine/moonraker](https://github.com/Arksine/moonraker)

本项目按 GPL-3.0 发布，详细来源及修改边界见 [THIRD_PARTY_NOTICES.md](../THIRD_PARTY_NOTICES.md)。

## 校验

Release 同时提供：

- `fluidd-acepro-card-ACEPROSV08-v1.0.0.zip`
- `SHA256SUMS.txt`

下载 ZIP 后可执行：

```bash
sha256sum -c SHA256SUMS.txt
```
