# Ace Pro Control Center | ACE Pro 管理中心

面向通用 Klipper 的 Anycubic ACE 第三代多设备驱动。正式版本名为 `V2.5ahpha`，最多支持 4 台 ACE 共用一个打印头和一条耗材路径。配置中的 `driver_version: 3` 表示第三代内部配置协议，不是产品版本号。

## 使用文档

面向安装、配置和日常使用的完整中文说明见 [GitHub Wiki 源文件](wiki/Home.md)。新用户建议从 [从零安装到首次打印](wiki/Beginner-Tutorial.md) 开始；只进行无动作安装可阅读 [快速开始](wiki/Quick-Start.md)。启用任何送料、回抽、切刀或自动换料动作前，请先阅读 [安全与限制](wiki/Safety-and-Limitations.md)。

## 当前能力

- ACE1：JSON/CRC/RPC、状态、四槽库存、送料、回抽、助推、烘干和换料编排。
- ACE2：共享总线、配置 UID、发现与地址绑定、状态读取；首版物理动作在 Manager 和协议层双重拒绝。
- 组合：`ACE1+ACE1`、`ACE1+ACE2`、`ACE2+ACE2`，配置顺序固定映射 `ace0..ace3 -> T0..T15`。
- 命令：`ACE_CHANGE_TOOL TOOL=T5`、`ACE_CHANGE_TOOL TOOL=TR`，并固定注册 `T0..T15` 与 `TR`；未就绪时提示后安全忽略。
- 安全：单一共享路径锁、上方传感器闭环终点、可选下方监测、五通停车确认、独立送料总超时、目标槽前置检查、ACE 与挤出机协同回抽、非幂等命令不重试、打印状态与能力门禁。
- 前端：V2 风格 Fluidd 管理卡片，多设备切换按钮，Fluidd 侧栏 `#/acepro` 完整页面，以及 `/ace-v3/` 静态备用页面。
- API：`GET /server/ace/status`、`GET /server/ace/capabilities`、`POST /server/ace/action`。

ACE1 是当前唯一具备实体设备验证条件的型号；驱动连接、只读状态、单 ACE 拓扑和前端已经部署验证，送料、回抽、切刀和自动换料仍需逐项完成真机物理动作验收。ACE2 只有协议模拟和只读实现，尚无本地实体设备验证条件。

## 多 ACE 汇流拓扑

单 ACE 使用单级路径，四槽直接进入 1 个总五通，不需要一级五通。只有安装第 2 台 ACE 后才启用两级汇流：每台 ACE 使用 1 个一级五通，再共同进入 1 个总五通。因此 2/3/4 台 ACE 分别需要 3/4/5 个五通；多 ACE 两级路径已经通过本地模拟，尚未完成真机物理动作验收。

- 单 ACE 主路径为：`ACE 槽位 -> 总五通 -> 可选共享编码器 -> 上方传感器 -> 挤出机 -> 喷嘴`；下方传感器是可选观测点，默认不参与控制。多 ACE 才在 ACE 槽位与总五通之间增加每设备一级五通。ACE 设备内部自行完成张力调节，V3 不提供独立缓冲器节点、参数或界面。
- 旧 `rdm_sensor_*` 配置名继续兼容，界面和文档统一称为“总五通传感器”。一级五通传感器只属于 2 至 4 台 ACE 的多设备拓扑。
- 总五通使用 `rdm_sensor_debounce_count`；多 ACE 的一级五通共同使用 `ace_hub_sensor_debounce_count`，两者互不替代。
- 单 ACE 的全部 `aceN_hub_*` 配置均保持为空并由运行时忽略。多 ACE 未安装一级传感器时，必须为对应 `aceN` 实测受限盲回退距离。
- 跨设备换料必须先确认旧料已经退出当前一级分支并释放总五通，之后才允许另一台 ACE 送料。

## 共享编码器

V3 可选使用一个共享耗材编码器，直接安装在总五通之后、上方传感器之前的公共路径。ACE Pro 使用直流送料电机，协议送料量只能作为固件参考，不能表示耗材真实位移；ACE 阶段编码器只判断“是否有实际移动”，上方传感器稳定触发才是唯一成功终点。上方触发后由挤出机步进电机接管，此时编码器才比较实测位移与命令距离。编码器不能判断路径中是否有料，不能替代上方或五通传感器，也不会自动追加送料或补偿打滑。

- `encoder_sensor_pin`：共享编码器脉冲引脚；未安装时留空。内部对象名由驱动固定创建，用户无需填写。
- `encoder_resolution`：每个脉冲对应的毫米数；`0` 表示尚未校准，配置值必须是有限的非负数。
- `encoder_detection_length`：ACE 的每个受限窗口都会检查零脉冲；该值规定长窗口的最小脉冲门槛及挤出机跟随率检测下限，默认 `20 mm`，不是 ACE 的到位距离。`protect` 模式要求挤出机保证运动距离不小于此值。
- `encoder_min_tracking_ratio`：只用于挤出机步进段，实测位移与命令距离之比低于该值时报告跟随不足，默认 `0.6`。
- `encoder_mode`：`off` 完全关闭，`monitor` 只记录，`protect` 在未确认移动时中止当前动作。默认 `off`；`protect` 只有在编码器可用且已校准后才允许自动换料进入就绪状态。
- `encoder_print_mode`：独立控制打印中连续监测；`off` 关闭，`monitor` 只记录并提示，`pause` 还会通过错误处理宏请求暂停一次。默认 `off`。
- `encoder_print_detection_length`：打印净挤出累计到该距离仍没有新脉冲时生成故障，默认 `20 mm`，必须是有限正数。回抽与随后恢复的距离不会累计。

编码器校准采用三段式人工测量：每段默认准确移动 `150 mm`，默认完成 `3` 段，并分别记录脉冲数与 `mm/脉冲`。段间最大偏差不超过 `5%` 时通过；大于 `5%` 且不超过 `10%` 时显示警告并允许保存；超过 `10%`、任一段脉冲不足或数据无效时拒绝保存。校准只计算分辨率并保存到 V3 运行状态，不改写 `ace.cfg`，也不驱动 ACE 或挤出机。开始、逐段提交和取消均要求打印机待机、当前耗材已卸载、共享路径为 `empty` 且辅助送料关闭；Fluidd 控制台在脉冲增加时同步显示本段新增、本段累计和硬件累计计数。校准段长用于提高测量可信度，不得替代运行时检测窗口；ACE 动作和打印中的打滑检测仍使用 `encoder_detection_length` 与 `encoder_print_detection_length` 的短窗口。

打印连续监测只在 `print_stats=printing`、路径已有装载工具、没有换料事务且不在校准时运行。未安装编码器时静默停用，不影响 Klipper 启动或普通打印。故障记录会保留工具、设备、路径、打印和传感器现场，并给出仅供排查的可能原因；它不会自动送料、补偿距离或恢复动作。

ACE 自动装载始终以上方传感器稳定触发为终点，并受 `upper_sensor_feed_timeout` 独立硬超时保护，默认 `30` 秒。主参考量和低速参考量均拆成受限窗口；预设参考量耗尽后仍以低速窗口继续寻找传感器，但绝不越过总超时。触发后立即停止 ACE，再由挤出机执行 `toolhead_sensor_bypass_load_length` 标定距离。模板中的 `25 mm` 只是醒目的“未校准样板”；用户完成本机重复测量并将 `toolhead_sensor_bypass_calibrated` 改为 `True` 前，自动换料保持未就绪。`toolhead_sensor_bypass: True` 是新安装默认值，表示下方传感器即使接线也只读取显示；确认该传感器长期稳定后，可显式改为 `False` 启用下方闭环。

## 安装

在打印机 Linux 主机上运行：

```bash
git clone https://github.com/Luomo520/ace-pro-control-center.git ~/ace-pro-control-center
cd ~/ace-pro-control-center
./installer/install.sh \
  --non-interactive \
  --device-count 1 \
  --device 'ace1|/dev/serial/by-id/REPLACE_WITH_STABLE_PATH'
```

安装器会链接 Klipper extra、Moonraker 组件和独立页面，并生成或升级唯一活动配置 `ace.cfg`。`printer.cfg` 运行时只需要 `[include ace.cfg]`；`ace.cfg` 同时包含硬件拓扑、共享参数、机器钩子和机器宏，不再 include 其他 ACE 配置文件。新安装默认写入 `toolchange_mode: manual`，ACE1 默认关闭物理动作，七个必用名称绑定默认全部启用。

首个 GitHub 公开版本的用户直接执行全新安装，不需要准备拆分配置。硬件拓扑块由安装器管理；重装时按稳定硬件身份保留每台设备的 `enabled`、`rfid_enabled` 和 `physical_actions_enabled`，同时保留用户已有的运行模式、引脚、距离、坐标和自定义宏。增删 ACE、替换型号或改变组合时重新运行同一安装命令。安装器不会重启服务或执行物理动作。

检测到其他 ACE 实现、冲突工具宏或来源不明的配置时，安装器会停止而不会覆盖；应先确认冲突文件的来源，再处理并重新安装。

安装前可以只运行兼容性探测：

```bash
./installer/install.sh --check-compatibility \
  --klipper-python ~/klippy-env/bin/python \
  --fluidd-source ~/fluidd-source \
  --fluidd-mode auto
```

Klipper 采用 API 能力探测，要求其实际运行 Python `>=3.8` 且可导入 `pyserial >=3.4`。安装器自动识别现代 `~/printer_data/config` 和旧式 `~/klipper_config`；厂商目录可通过 `--klipper-home`、`--moonraker-home`、`--config-dir`、`--fluidd-home` 和 `--klipper-python` 明确指定。详细矩阵见 `docs/COMPATIBILITY.zh-CN.md`。

当前能力探测已用上游 Klipper `v0.10.0`、`v0.11.0`、`v0.12.0`、`v0.13.0` 和提交 `d865997` 验证。版本号仅用于诊断，厂商固件仍必须通过实际源码 API 与运行环境检查；安装器不会自动升级 Klipper、Python、pyserial、Node 或 Fluidd。

ACE2 安装必须提供明确 UID；自动发现结果尚未安全持久化，因此当前版本拒绝 `device_uid: auto`。

可先验证而不写入：

```bash
./installer/install.sh --dry-run --non-interactive \
  --device-count 2 \
  --device 'ace1|/dev/serial/by-id/ACE_ONE' \
  --device 'ace2|/dev/serial/by-id/ACE_TWO|ace2bus0|1:2:3'
```

使用源码版 Fluidd 集成时追加 `--fluidd-source /path/to/fluidd`。默认 `--fluidd-mode auto`：官方 Fluidd `1.34.x-1.37.x` 且源码能力匹配时补丁 Dashboard、`/acepro` 路由和侧栏入口；更旧、更新或厂商修改过的未知结构自动回退 `/ace-v3/` 独立页面。使用 `--fluidd-mode source` 可要求不兼容时直接失败，使用 `standalone` 可明确禁止源码修改。源码补丁后需要按该 Fluidd 版本自身工具链重新构建并部署 `dist`。

Fluidd 源码集成已用官方 `1.34.4`、`1.35.1`、`1.36.4` 和 `1.37.3` 验证。`auto` 回退不会修改不兼容的 Fluidd 源码；`source` 会在安装事务写入前失败；`standalone` 始终只部署独立页面。

正式安装必须在写入前创建独立、持久化且带时间戳的安装前快照，并在安装结果中打印快照路径、恢复命令和恢复范围。该快照不能依赖安装事务结束时会删除的临时回滚目录；安装失败时自动回滚，安装成功后仍须保留快照供人工恢复。

卸载：

```bash
./installer/uninstall.sh
```

卸载只移除 V3 自身链接和托管块，保留用户的 `ace.cfg`、`.ace-driver-v3/legacy/` 迁移归档与其他配置。

## 动作前配置

通用驱动不能猜测打印机坐标、温度、切刀和传感器引脚。新安装可先保持手动模式，只使用状态与库存；启用自动换料前完成：

- 在 `ace.cfg` 填写上方、下方和总五通的真实 `*_pin`；只有安装 2 至 4 台 ACE 时才填写实际设备对应的一级五通 pin。空 pin 表示不启用该传感器，内部对象名由驱动管理。
- 需要耗材运动监测时，在总五通之后的公共路径安装编码器，先保持 `encoder_mode: off` 完成人工校准，再选择 `monitor` 或 `protect`。
- V3 不使用尖端成型，自动换料必须通过切刀退出旧料。`cut_macro` 名称绑定默认启用，但真实切刀动作仍是注释样板；必须按本机核对坐标、方向和速度后，才能取消 `_ace_cut_filament` 实现的注释。
- `ace.cfg` 的换料前处理、切刀、送料、回料、擦嘴、换料后处理和故障暂停七个绑定全部默认启用，并统一使用 `!!!【必用】`；缺少任一能力时自动换料不可用。前处理、切刀、擦嘴和后处理的机器动作实现仍保持整段注释，必须按本机配置并验证。上下路径传感器可读取且全部预检通过后，再将 `toolchange_mode` 改为 `automatic`。

LOAD/UNLOAD 宏只进入驱动的传感器路径控制器；实时停止、分段送料和交替回抽不由 Jinja 宏循环实现。传感器或必用宏缺失时连接和状态读取仍可用，但自动换料会保持“尚未就绪”。`require_cut_hook` 默认开启；它和 `cut_macro` 绑定只声明自动换料必须使用哪个宏，不会启用任何样板坐标。只有取消对应 `[gcode_macro _ace_cut_filament]` 实现的注释后，切刀动作才可能被调用。

单 ACE 没有总五通传感器时，`toolchange_retract_length` 仍作为回抽依据，不读取任何一级五通字段。多 ACE 自动换料必须具备可验证的分支清空方案：总五通有效，且每台可执行物理动作的 ACE 使用一级五通传感器，或填写经过实测的 `aceN_hub_retract_length` 与 `aceN_hub_clear_move_length`。任何模板距离都不能视为通用校准结果。

ACE 内置辅助送料独立于自动换料。打印中直接启用必须执行 `ACE_ENABLE_FEED_ASSIST TOOL=T0 CONFIRM=1`，停用使用 `ACE_DISABLE_FEED_ASSIST`；Fluidd 的确认对话框会自动传递该确认。自动换料装载前会先停用活动辅助送料，停用失败时中止换料。

## 本地验证

```bash
python -m pytest -q
node --test tests/frontend/*.test.mjs
python scripts/test_release.py
python scripts/validate_release.py --repo . --require-frontend
bash scripts/test_installer.sh
```

Windows Git Bash 只能执行安装器 dry-run；真实符号链接安装、卸载和回滚仍需在 Linux/Klipper 主机验证。

当前本地源码基线为 Python `368 passed`（另有 `3 subtests passed`）、前端 Node `55 passed`、发布契约 `27 passed`，完整发布树校验与 Python 编译检查通过。Linux 安装、重复安装、卸载、冲突回滚、旧配置迁移和 Fluidd 模式回退已在打印机 `/tmp` 隔离目录通过集成测试；两级五通、共享编码器、单 ACE 拓扑和前端已经部署到目标打印机并完成只读验证。目标打印机只有 1 台 ACE，因此这些结果不代表多 ACE 或任何送料、回抽、切刀、换料动作已经通过真机验收。

## 本机多设备界面模拟

在项目根目录启动静态服务：

```bash
python -m http.server 8770 --bind 127.0.0.1
```

打开 `http://127.0.0.1:8770/frontend/simulator/`。模拟器包含 Fluidd Dashboard 卡片、Fluidd 侧栏完整页和 `/ace-v3/` 备用控制页，可切换 1-4 台设备、ACE1/ACE2 组合、连接状态、两级五通和共享编码器状态。所有交互只修改浏览器内存中的模拟状态，不连接 Moonraker，也不会向打印机发送命令。

## 上游来源

- 后端架构参考：[Kobra-S1/ACEPRO](https://github.com/Kobra-S1/ACEPRO) `221f27b92f2eee39e3b8eacf7c3c3b198237b972`
- ACE1 行为与界面参考：[szkrisz/ACEPROSV08](https://github.com/szkrisz/ACEPROSV08) `0311eb375cb7f14d41a8e2029d4a6d7363c6ceba`
- 配置排版与编码器机制参考：[moggieuk/Happy-Hare](https://github.com/moggieuk/Happy-Hare) `73d39aab2110deebb64dfb7899c6838a706edcea`
- 许可证：GPL-3.0-only，详见 `THIRD_PARTY_NOTICES.md`。

详细设计见 `docs/DECISIONS.zh-CN.md`、`ARCHITECTURE.zh-CN.md`、`CONFIGURATION.zh-CN.md`、`COMPATIBILITY.zh-CN.md`、`FRONTEND.zh-CN.md` 和 `TESTING.zh-CN.md`。
