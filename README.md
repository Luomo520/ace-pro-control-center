# fluidd-acepro-card-ACEPROSV08

> 仅适配 `szkrisz/ACEPROSV08` 的单台 ACE Pro、四料槽方案。
> 不兼容 `Kobra-S1/ACEPRO`，请勿同时加载两套驱动配置。

这是面向 DIY Klipper 打印机的一体化 ACE Pro 套件。一个安装器同时部署增强版 ACEPROSV08 驱动、配置模板、Moonraker 受控 API、Fluidd 仪表盘卡片和中文 `/ace.html` 辅助页面。

![ACE Pro Fluidd 卡片](docs/images/fluidd-acepro-card.png)

## 版本与兼容性

| 项目 | 当前版本 |
| --- | --- |
| 套件 | `v0.3.0` |
| 驱动 | `ACEPROSV08 0.3.0-luomo`，基于 `szkrisz/ACEPROSV08` |
| Fluidd | 基于 `v1.37.2` 完整源码构建 |
| ACE 数量 | 1 台 |
| 料槽 | 4 个 |
| 语言 | 简体中文 |
| 许可证 | GPL-3.0 |

## 主要卖点

- 一次安装完整链路，不再分别手动复制 Klipper 驱动、Moonraker 组件和 Fluidd 文件。
- 每次安装、更新和卸载都先把旧文件移动到带时间戳的 `old/` 归档；失败自动恢复，不直接删除用户文件。
- 默认更新保留机器现有 `ace.cfg`，新版参数模板单独放在 `~/ACEPROSV08/ace.cfg.example`。
- 快速送料、末段慢速接近和有限打滑补偿兼顾效率与可靠性；快速阶段不再每 100 mm 停顿。
- 送料失败暂停打印而不是取消任务，并报告换料方向、失败阶段、已移动距离和传感器状态。
- ACE 断联恢复采用有界重试和传感器协调，禁止无条件重放不确定的物理动作。
- Fluidd 卡片与 `/ace.html` 使用同一组白名单 API，库存命令严格采用 ACEPROSV08 的 `INDEX` 参数。
- 中文显示设备、烘干、四槽库存、上下传感器、装卸、手动送料/回抽、无限续料和诊断状态。

## 驱动更新要点

- ACE 长距离送料：默认快速段 `160 mm/s`，最后 `200 mm` 以 `25 mm/s` 接近上方传感器。
- 打滑补偿：正常路径结束后最多补偿 `400 mm`，每段 `50 mm`，达到上限立即暂停并提示阶段。
- 工具头送料：上方传感器触发后先按 `5 mm` 分段送料，再按 `1 mm` 分段寻找下方传感器。
- 回收优化：默认快速回收 `120 mm/s`，最后 `200 mm` 降至 `25 mm/s` 停放。
- 换料状态：显示 `TA -> TB`、切刀阶段、回收阶段、送料阶段和最终槽位。
- 连接恢复：记录连接代次、最后断联原因、换料上下文和恢复状态，避免无限重试。
- 库存输出：`ACE_QUERY_SLOTS` 使用统一缩进的中文四槽信息。
- 配置模板：顶部包含路径示意图、必填参数、速度和距离的中文注释。

完整说明见 [驱动 v0.3.0 更新与调校](docs/DRIVER-v0.3.0.zh-CN.md)。

## 快速安装

在打印机 SSH 中执行：

```bash
cd ~
git clone --depth 1 https://github.com/Luomo520/fluidd-acepro-card-ACEPROSV08.git
cd fluidd-acepro-card-ACEPROSV08
sh install.sh
```

字符菜单提供：

```text
1. 安装 / 更新整套组件（默认：驱动 + 卡片，保留 ace.cfg）
2. 仅安装 / 更新 ACEPROSV08 驱动和配置
3. 仅安装 / 更新 Fluidd 卡片和 Moonraker 适配层
4. 整套安装并使用新版 ace.cfg 模板
5. 强制整套安装（跳过现有驱动/API 判断）
6. 回滚到上一次安装前版本
7. 卸载并恢复首次安装前版本
8. 检查安装状态
9. 退出
```

默认选择 `1` 会同时安装驱动和卡片。选择 `2` 不修改 Fluidd/Moonraker，选择 `3` 不修改 Klipper 驱动和 `ace.cfg`。只有准备重新标定全部路径、针脚和切刀坐标时才选择 `4`。强制安装不会跳过文件校验、`old/` 归档和失败恢复。

整套安装和仅卡片安装会比较当前 Fluidd 版本与本包测试版本 `v1.37.2`：低版本会提示升级风险，高版本会提示降级风险，无法识别版本也会要求确认。用户取消时不会移动或修改任何目标文件。若安装后发现兼容问题，可执行 `sh ui-installer.sh --rollback-latest` 按最近一次安装范围回滚；首次安装前的完整恢复仍使用卸载选项。

安装器不会自动重启服务。确认没有打印任务后执行：

```bash
sudo systemctl restart klipper
sudo systemctl restart moonraker
```

然后访问：

- Fluidd：`http://打印机IP/`
- 独立辅助页：`http://打印机IP/ace.html`
- API 状态：`http://打印机IP:7125/server/ace/status`

完整步骤见 [安装、升级与恢复教程](docs/INSTALL.zh-CN.md)。

## 安装前必查

全新安装后、重启 Klipper 前，必须检查 `~/printer_data/config/ace.cfg`：

1. `serial`：优先使用 `/dev/serial/by-id/...`。
2. `extruder_sensor_pin`：上方传感器 MCU 针脚。
3. `toolhead_sensor_pin`：下方传感器 MCU 针脚。
4. `toolchange_load_length`：ACE 停放位置到上方传感器的最大送料距离。
5. `toolchange_retract_length`：足以释放公共通道的回收距离。
6. `bowden_tube_length`：ACE 到汇合点的实际管路长度。
7. `toolhead_sensor_to_nozzle`：下方传感器到喷嘴的距离。
8. `CUT_TIP` 坐标：必须按本机切刀位置填写，禁止照抄示例坐标。

## old 归档与卸载

归档位置：

```bash
~/.local/share/aceprosv08-ui/old/
```

每个时间戳目录只包含该次安装范围内被移动的文件和路径清单。整套、仅驱动、仅卡片分别保存首次安装基线，互不覆盖；`manifest.txt` 中的 `scope` 记录实际范围。

卸载：

```bash
cd ~/fluidd-acepro-card-ACEPROSV08
sh uninstall.sh
```

卸载前仍会归档当前版本，再恢复首次安装前状态。

只撤销最近一次更新：

```bash
sh ui-installer.sh --rollback-latest
```

## 更新

```bash
cd ~/fluidd-acepro-card-ACEPROSV08
git pull --ff-only
sh install.sh
```

选择菜单 `1` 即可保留现有机器参数并更新整套组件。不要用压缩包覆盖旧目录；Git 更新便于核对来源和版本。

## 验证

本版本验证范围：

- Fluidd 类型检查通过。
- Fluidd 14 个测试文件、326 项单元测试通过。
- ESLint 无错误；有 2 条非阻断格式警告。
- Fluidd v1.37.2 生产构建和 PWA Service Worker 构建通过。
- Python 驱动、Moonraker 组件编译和 API 契约测试。
- Shell 语法、版本取消提示、整套安装、仅驱动、仅卡片、强制更新、`old/` 归档、失败恢复和按范围回滚。

## 限制

- 仅支持单台 ACE Pro 和四个料槽。
- 安装器不会自动执行 `T0`、`T1`、切刀、送料或回抽测试。
- 模板中的速度和距离是起点，不是所有 DIY 机器的通用标定值。
- Fluidd 卡片是完整 Fluidd 构建产物，不是浏览器扩展；升级官方 Fluidd 后需重新运行本安装器。

## 开源说明

本项目依据 GPL-3.0 发布，保留 `szkrisz/ACEPROSV08`、`Kobra-S1/ACEPRO` 和 `fluidd-core/fluidd` 的来源与许可说明。详见 [第三方来源声明](THIRD_PARTY_NOTICES.md)。
