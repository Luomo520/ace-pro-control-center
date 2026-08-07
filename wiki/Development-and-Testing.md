# 开发与测试

本页面向驱动维护者和贡献者。普通用户安装和使用 Ace Pro Control Center 不需要运行本页的测试服务器、模拟器或发布脚本。

## 开发环境

后端最低要求：

- Python `>=3.8`
- `pyserial >=3.4`
- 可运行的 Klipper 与 Moonraker 源码环境

原生 Fluidd 集成还需要目标 Fluidd 版本自己的 Node 和包管理器工具链。不要为了构建 ACE 卡片擅自升级打印机上的 Node 或替换整个 Fluidd 目录。

安装 Python 依赖后，从项目根目录运行测试。建议在与打印机隔离的开发机或虚拟环境中完成大部分验证。

## 标准验证命令

```bash
python -m pytest -q
node --test tests/frontend/*.test.mjs
python scripts/test_release.py
python scripts/validate_release.py --repo . --require-frontend
bash scripts/test_installer.sh
```

各命令用途：

| 命令 | 覆盖范围 |
| --- | --- |
| `python -m pytest -q` | 协议、配置、状态机、安全门禁、路径、编码器、Moonraker API 和 Fluidd 补丁单元测试 |
| `node --test tests/frontend/*.test.mjs` | 共享前端核心、API 客户端、工具提示、工具号裁剪和 UI 契约 |
| `python scripts/test_release.py` | 发布脚本、配置预检、打包和托管块契约 |
| `validate_release.py` | 发布树静态结构、配置模板、Python 入口和前端资产一致性 |
| `test_installer.sh` | Linux 安装、重复安装、迁移、卸载、回滚和 Fluidd 模式 |

Windows Git Bash 适合运行安装器 dry-run；真实软链接、权限、服务目录和回滚行为仍应在 Linux 或 Klipper 主机的隔离目录中验证。

## 发布树校验

提交或打包前必须运行：

```bash
python scripts/validate_release.py --repo . --require-frontend
```

校验器主要检查：

- `ace_driver`、Moonraker 组件和 Klipper wrapper 的入口函数存在，所有 Python 文件可解析。
- 安装器与安装测试声明相同的 wrapper 列表。
- `config/` 中不存在退役的活动 `ace_hardware.cfg`。
- `config/ace.cfg` 包含 `[ace]`、`[ace_machine]`、设备与硬件拓扑，并保持新安装默认 `toolchange_mode: manual`。
- 七个机器动作绑定名称正确，切刀为必用项；涉及本机坐标的物理宏样板默认整段注释。
- 用户配置模板只暴露传感器引脚，不重新要求旧版 `*_sensor_name`。
- 不重复注册驱动拥有的 `T0-T15` 或 `TR`，不保留旧 `ace_hardware.cfg`、`ace_machine.cfg` include。
- 独立页面的缓存版本一致，用户界面不再使用独立“缓冲器”概念。
- Dashboard、共享前端核心、Fluidd 卡片、槽位组件和 `AcePro` 页面齐全。
- 独立页面与 Fluidd overlay 的 `ace-core.js` 逐字节一致。

不带 `--require-frontend` 时只检查后端和配置发布契约；正式发布必须带该参数。

## 后端测试重点

协议与设备：

- ACE1 帧头、长度、CRC、请求 ID、分包、超时和异常响应。
- ACE2 解码、UID、能力声明和只读门禁。
- 1 至 4 台设备的连续编号、稳定工具映射、重复串口和总线身份校验。
- 串口超时期间 Reactor 仍可调度，非幂等物理命令不自动重发。

换料与共享路径：

- `ace0..ace3` 稳定映射为 `T0..T15`。
- 手动模式逐条忽略 `T0-T15/TR` 并记录提示，不暂停打印。
- 自动换料任一必用宏预检失败时，不得向 ACE 发送部分物理动作。
- 多设备轮询可以并行，但单打印头的真实耗材路径动作必须串行。
- 单 ACE 不创建一级五通；多 ACE 覆盖全传感器、仅总五通和逐设备盲回退方案。

编码器：

- 脉冲累计、默认 `150 mm x 3` 分段校准、逐段结果、取消、范围边界和重复开始拒绝。
- 三段最大偏差 `<=5%` 通过、`>5%` 且 `<=10%` 警告确认、`>10%` 或任一段脉冲不足拒绝保存，并保留上一次有效校准。
- 校准期间及打印中的动作门禁。
- `monitor` 只记录，`protect` 中止 ACE 动作，不自动追加送料。
- ACE 动作与打印监测保持短窗口，不得复用 `150 mm` 校准段长；打印监测按净挤出累计，回抽与恢复抵消，`pause` 每个事件只请求一次暂停。

## API 与前端测试重点

- 三个 `/server/ace/...` 端点返回统一成功和错误结构。
- HTTP 动作只接受固定白名单和参数，不接受原始 G-code。
- 确认、打印状态、设备在线、ACE2 只读、能力和共享路径锁由 Moonraker 再次校验。
- 单 ACE 只显示 `T0-T3`；2、3、4 台分别显示 8、12、16 个按钮，每台一行四列。
- Dashboard、`#/acepro` 和 `/ace-v3/` 使用相同工具、库存、能力和阻塞原因。
- API 失败不会回退为控制台命令，页面刷新和网络重连不会重复物理动作。
- 桌面与移动宽度下无槽位错列、文字溢出、按钮重叠或卡片嵌套错误。

## Fluidd 源码兼容测试

原生集成不仅检查版本号，还检查 Dashboard 注册、布局、路由、侧栏和工具命令区锚点。维护兼容 profile 时至少完成：

1. `scripts/fluidd_overlay.py inspect` 能唯一识别目标源码。
2. `check`、`apply`、重复 `apply` 和 `remove` 均通过。
3. TypeScript 检查通过。
4. 使用目标 Fluidd 自己的工具链完成生产构建。
5. 构建产物中 Dashboard 卡片、`#/acepro`、侧栏入口和单 ACE 工具裁剪可见。
6. 已有 V2 路由可以迁移并在移除 V3 时恢复；未知冲突必须失败关闭。

不兼容的 Fluidd 在 `auto` 模式下应保留 `/ace-v3/`，不能影响后端安装。

## 本地界面模拟器

模拟器用于开发布局和状态组合，不是用户安装步骤，也不能替代 Moonraker、Klipper 或真机测试。

```bash
python -m http.server 8770 --bind 127.0.0.1
```

打开：

```text
http://127.0.0.1:8770/frontend/simulator/
```

模拟器可以切换 Dashboard 卡片、完整页、备用页、1 至 4 台设备、ACE1/ACE2 组合、连接状态、五通和编码器场景。所有操作只修改浏览器内存，不连接打印机，也不会发送命令。

## 真机验证门槛

本地测试通过不等于物理动作通过。真机测试应按以下顺序逐项记录设备型号、配置、日志、结果和是否发生物理动作：

1. 设备识别和只读轮询。
2. 手动刷新和断线恢复。
3. 上方、总五通及多设备一级五通电平；可选下方传感器只验证原始显示。
4. ACE 命令距离不参与位置判断、上方稳定触发停止和最大送料时间硬停止。
5. 共享编码器脉冲、默认 `150 mm x 3` 人工校准、一致性门禁和取消，以及 ACE 寻位段和挤出机接管段的短窗口 `monitor`。
6. 烘干、短距离送料和短距离回料。
7. 编码器在 ACE/挤出机两段的 `protect` 故障路径和打印 `pause` 故障路径。
8. 切刀、擦嘴、完整换料和恢复流程。
9. 多设备分支清空与路径串行化。

服务重启或可能发生机械动作前必须确认 `print_stats` 不在打印。修改打印机配置前后应按项目维护规则建立备份。

当前目标机只完成单 ACE 页面和只读状态验证时，不得把以下内容写成已通过真机验收：

- 多 ACE 的真实分支清空和物理并发。
- ACE2 的送料、回料、烘干、辅助送料或换料。
- 未逐项验证的切刀、擦嘴和喷嘴侧坐标。
- 仅由模拟脉冲证明的编码器 `protect` 或打印 `pause`。

## 合并要求

合并前至少满足：

- 标准验证命令全部通过，或在变更说明中明确记录无法运行的项目和原因。
- 新命令同步更新 Klipper 命令测试、Moonraker 白名单、前端能力模型和本 Wiki。
- 新状态字段保持 JSON 可序列化，并具有旧状态缺失时的降级行为。
- 不引入第二套工具映射、换料状态或前端直接 G-code 回退。
- 文档明确区分“已实现”“已模拟测试”和“已真机验证”。
