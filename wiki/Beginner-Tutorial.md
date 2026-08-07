# 从零安装到首次打印

本教程面向第一次从 GitHub 安装 Ace Pro Control Center 的用户，适用于 `V2.5ahpha`。公开用户直接按全新安装流程操作。

教程分为两个阶段：

- **阶段一：安装和只读验收。** 完成后可以查看 ACE、槽位、RFID、传感器和 Fluidd 页面，不会执行送料、回料、切刀或换料。
- **阶段二：物理动作和自动换料。** 需要逐项配置传感器、路径距离和七个机器宏，完成真机验收后才能用于多色打印。

只想先安装驱动的用户做到第 6 节即可。准备自动换料时，再从第 7 节继续。

> **严重警告：** 切刀、擦嘴、工具头移动、送料和回料都可能造成撞机、堵头、磨料、断料或线盘缠绕。文档中的引脚、距离、温度和坐标都不是你的机器参数。未经本机核对，不得直接运行样板动作。

## 1. 安装前准备

开始前确认：

- 打印机处于待机状态，没有正在打印、暂停等待恢复或正在执行的换料任务。
- 已备份 `printer.cfg`、`moonraker.conf`、机器宏和 Fluidd 自定义内容，并知道如何恢复。
- 可以通过 SSH 或终端登录打印机 Linux 主机。
- 已下载 GitHub Release 中的 `Ace-Pro-Control-Center.tar.gz`。
- Klipper 实际运行 Python `3.8` 或更高版本，并可导入 `pyserial 3.4` 或更高版本。
- 已确定 ACE 数量、型号和接入顺序。

当前版本最多支持 4 台 ACE 共用一个打印头和一条公共耗材路径。设备顺序固定决定工具号：

| 安装顺序 | 配置名称 | 工具号 |
| --- | --- | --- |
| 第 1 台 | `ace0` | `T0-T3` |
| 第 2 台 | `ace1` | `T4-T7` |
| 第 3 台 | `ace2` | `T8-T11` |
| 第 4 台 | `ace3` | `T12-T15` |

每台 ACE 的四个物理槽位按顺序映射：第 1 槽对应该设备范围内的第一个工具号，第 2 槽对应下一个工具号。例如 ACE 1 的四槽是 `T0/T1/T2/T3`，ACE 2 的四槽是 `T4/T5/T6/T7`。

ACE1 已具备连接、状态和物理动作实现；所有物理动作仍需用户在自己的机器上验收。ACE2 当前只支持协议模拟和只读状态，驱动会拒绝 ACE2 物理动作。多 ACE 配置和界面已经实现，但多机物理路径尚未完成真机验收，不应直接用于无人值守打印。

## 2. 获取完整安装文件

推荐直接从正式仓库克隆：

```bash
git clone https://github.com/Luomo520/ace-pro-control-center.git ~/ace-pro-control-center
cd ~/ace-pro-control-center
chmod +x installer/install.sh installer/uninstall.sh
```

也可以使用 Release 压缩包。将 `Ace-Pro-Control-Center.tar.gz` 上传到打印机用户的主目录，可以使用 SFTP、Fluidd 文件传输工具或电脑上的 `scp`。登录打印机后执行：

Release 同时提供 `deploy-manifest.json` 时，先执行 `sha256sum ~/Ace-Pro-Control-Center.tar.gz`，将结果与清单中同名文件的 `sha256` 比较；不一致时重新下载，不要继续解压。

```bash
mkdir -p ~/ace-pro-control-center
tar -xzf ~/Ace-Pro-Control-Center.tar.gz -C ~/ace-pro-control-center
cd ~/ace-pro-control-center
chmod +x installer/install.sh installer/uninstall.sh
```

确认目录中至少存在：

```bash
ls installer config ace_driver frontend
```

如果压缩包不在主目录，替换 `tar` 命令中的实际路径。不要从压缩包内部单独复制几个 Python 文件，安装器需要完整目录结构。

## 3. 查找 ACE 串口

连接并开启 ACE，然后执行：

```bash
ls -l /dev/serial/by-id/
```

记录每台 ACE 的完整路径，例如：

```text
/dev/serial/by-id/usb-REPLACE_WITH_REAL_ACE_ID
```

可以在断开和重新连接 ACE 前后分别执行一次命令，以消失和重新出现的项目确认设备。不要使用 `/dev/ttyUSB0` 或 `/dev/ttyACM0`，这些短名称可能在重启或插拔后改变。

每台 ACE1 必须使用独占串口。ACE2 可以共享总线，但每台必须填写明确且唯一的 UID。首次安装建议明确选择 `ace1` 或 `ace2`，不要用 `auto` 猜测型号。

## 4. 运行兼容性检查

兼容性检查只读取环境，不写入打印机配置：

```bash
cd ~/ace-pro-control-center
./installer/install.sh --check-compatibility \
  --klipper-python ~/klippy-env/bin/python \
  --fluidd-mode auto
```

如果你的 Klipper Python 不在 `~/klippy-env/bin/python`，使用打印机实际路径替换。厂商固件、多 Klipper 实例或自定义目录可按[安装与升级](Installation-and-Upgrade#自定义目录与多实例)明确传入 `--klipper-home`、`--moonraker-home`、`--config-dir`、`--fluidd-home` 和 `--klipper-python`。

检查成功只表示软件接口和运行环境兼容，不表示 ACE 已经连接，也不表示任何物理动作已经启用。

## 5. 模拟安装和正式安装

### 交互式安装

先模拟安装：

```bash
./installer/install.sh --dry-run
```

单台 ACE1 的回答示例：

```text
ACE device count [1-4]: 1
ace0 model [ace1/ace2/auto]: ace1
ace0 stable serial path: /dev/serial/by-id/usb-REPLACE_WITH_REAL_ACE_ID
Fluidd source checkout for card overlay (blank to skip):
```

最后一项不知道如何填写时直接回车。安装器仍会部署 `/ace-v3/` 独立页面；只有提供兼容的 Fluidd 源码目录并完成重新构建后，才会出现原生 Dashboard 卡片和 `#/acepro` 页面。

检查模拟输出中的设备数量、顺序、型号、串口、Klipper 路径、配置目录和 Fluidd 模式。全部正确后正式安装：

```bash
./installer/install.sh
```

再次填写与模拟安装完全相同的内容。

### 单台 ACE1 的固定命令

希望保存可重复命令时，可以使用：

```bash
./installer/install.sh --dry-run --non-interactive \
  --device-count 1 \
  --device 'ace1|/dev/serial/by-id/usb-REPLACE_WITH_REAL_ACE_ID'
```

确认后移除 `--dry-run`：

```bash
./installer/install.sh --non-interactive \
  --device-count 1 \
  --device 'ace1|/dev/serial/by-id/usb-REPLACE_WITH_REAL_ACE_ID'
```

两台及以上设备的命令格式见[安装与升级](Installation-and-Upgrade#新安装示例)。增删 ACE 时重新运行安装器，并提供最终完整设备列表；不要手工复制或删除 `ace_device` 节。

安装器会：

- 安装 Klipper ACE extra 和兼容 wrapper。
- 安装 Moonraker `ace_status` 组件。
- 生成唯一活动配置 `ace.cfg`。
- 部署 `/ace-v3/` 独立页面。
- 在提供兼容 Fluidd 源码时准备原生卡片和页面补丁。

安装器不会重启服务，不会发送 G-code，也不会执行送料、回料、烘干、切刀或换料。

## 6. 完成只读验收

### 检查默认安全状态

正式安装后先不要点击任何动作按钮。打开打印机配置目录中的 `ace.cfg`，检查：

```ini
[ace_device ace0]
model: ace1
serial: /dev/serial/by-id/usb-REPLACE_WITH_REAL_ACE_ID
enabled: True
physical_actions_enabled: False

[ace]
toolchange_mode: manual
```

同时确认 `printer.cfg` 只有一条 ACE include：

```ini
[include ace.cfg]
```

`physical_actions_enabled: False` 拒绝该设备的物理动作，`toolchange_mode: manual` 不启动自动换料。两者必须保持原值，直到后续验收明确要求修改。

`ace.cfg` 顶部带 V3 管理标记的设备数量、型号、顺序和串口由安装器维护。以后增删设备或改变组合时重新运行安装器，不要手工重排设备。`physical_actions_enabled` 是允许用户在验收后修改的设备安全开关。

### 重启服务

再次确认打印机待机，然后使用该打印机原有的服务管理方式重启 Klipper 和 Moonraker。不要猜测厂商固件的服务名称。使用 Fluidd 源码集成时，还要按该 Fluidd 版本的工具链重新构建并部署 `dist`。

安装器正式写入后应输出持久快照路径、恢复命令、恢复范围和校验结果。先记录这些信息，再重启服务。只有临时回滚提示而没有持久快照时，不要进入物理动作验收。Fluidd 源码模式还必须确认新 `dist` 已部署到实际 Web 根目录；源码文件出现 ACE 组件不代表网页已经更新。

重启后在 Fluidd 控制台执行：

```gcode
ACE_GET_STATUS
ACE_REFRESH DEVICE=ace0
```

只读验收应满足：

- Klipper 为 `ready`，没有 ACE 配置错误。
- `device_count` 等于实际数量，单 ACE 只有 `ace0`。
- ACE 显示在线，四个槽位状态可以读取。
- 单 ACE 的有效工具范围是 `T0-T3`。
- 未填写引脚的传感器显示“未配置”，不会导致 Klipper 启动失败。
- RFID 没有识别到有效标签时显示关闭或无数据，不应显示为设备故障。
- `http://打印机地址/ace-v3/` 可以打开独立页面。
- 完成原生 Fluidd 集成后，Dashboard 卡片和 `http://打印机地址/#/acepro` 可以打开。

后端为了兼容切片固定注册 `T0-T15`，但界面必须按实际设备数量显示 4、8、12 或 16 个工具。单 ACE 若仍显示 16 个按钮，按[故障排查](Troubleshooting#单-ace-却显示了更多工具号)检查 `device_count`、Fluidd 构建和浏览器缓存。

完成本节后可以停下。驱动已经安装，但不会自动换料，也不会因为传感器或机器宏尚未填写而报启动错误。

需要调整库存材料候选项时，修改 `ace.cfg` 中的英文逗号分隔列表，例如：

```ini
material_types: PLA, PLA+, PETG, ABS, ASA, TPU, PA-CF
```

可以按实际材料增删。RFID 默认允许读取，但未识别到有效标签时显示关闭或无数据；此时仍可在 Fluidd 卡片或完整页面中手工填写材料、颜色和温度。

## 7. 选择使用方式

| 使用方式 | 保持或修改的设置 | 适用场景 |
| --- | --- | --- |
| 只读管理 | `manual`、`physical_actions_enabled: False` | 查看设备、槽位、RFID 和传感器 |
| ACE 辅助送料 | 保持 `manual`，完成路径验收后只授权目标 ACE1 | 单色打印，使用 ACE 内置缓冲和助推 |
| 自动换料 | 最后改为 `automatic`，并通过全部就绪检查 | 已配置切刀和路径的多色打印 |

ACE 未配置、手动模式或自动换料未就绪时，切片中的 `T0-T15` 和 `TR` 会逐条显示中文提示后被忽略，不会暂停或拒绝打印，也不会改变路径状态。此时只允许只读管理和已经授权的 ACE 内置辅助送料；单色文件可以继续，多色文件会在没有实际换色的情况下继续打印成错误颜色。

如果只需要辅助送料，检查第 8 节的实际耗材路径后直接按第 13 节完成短动作验收；自动换料专用的传感器、距离和机器宏可以暂不配置。已经接线的传感器仍可保留为只读监测。需要自动换料时继续按顺序完成全部章节。

## 8. 认识耗材路径

### 单 ACE

```text
ACE0 四槽 -> 总五通 -> 可选共享编码器 -> 上方传感器 -> 挤出机 -> 喷嘴
                                                                    └-> 可选下方传感器（只读）
```

单 ACE 只使用一个总五通，不使用一级五通。

### 多 ACE

```text
ACE0 四槽 -> 一级五通 0 --\
ACE1 四槽 -> 一级五通 1 ---+
ACE2 四槽 -> 一级五通 2 ---+--> 总五通 -> 可选共享编码器 -> 上方传感器 -> 挤出机 -> 喷嘴
                                                                                       └-> 可选下方传感器（只读）
ACE3 四槽 -> 一级五通 3 --/
```

| ACE 数量 | 一级五通 | 总五通 | 五通总数 |
| --- | --- | --- | --- |
| 1 | 0 | 1 | 1 |
| 2 | 2 | 1 | 3 |
| 3 | 3 | 1 | 4 |
| 4 | 4 | 1 | 5 |

ACE 自带缓冲和张力调节机构。V3 不配置额外的“ACE 缓冲器”，也不能把 Happy Hare 或 AFC 的外置缓冲器参数直接套用到 ACE。

## 9. 配置并验证传感器

用户只填写引脚，传感器名称由驱动固定创建。打开 `ace.cfg` 的 `[ace]` 区域：

```ini
extruder_sensor_pin: <上方传感器真实引脚>
extruder_sensor_debounce_count: 2

toolhead_sensor_pin: <可选下方传感器真实引脚；未安装时留空>
toolhead_sensor_debounce_count: 2
toolhead_sensor_bypass: True

rdm_sensor_pin: <总五通传感器真实引脚；未安装时留空>
rdm_sensor_debounce_count: 3

ace0_hub_sensor_pin:
ace1_hub_sensor_pin:
ace2_hub_sensor_pin:
ace3_hub_sensor_pin:
ace_hub_sensor_debounce_count: 3
```

尖括号内容是说明，不能原样保留。没有安装的传感器让冒号后保持为空。Klipper 引脚可以按真实电路使用 `^` 上拉和 `!` 反相，但必须查阅本机主板、工具板和传感器资料，禁止照搬其他打印机引脚。

传感器职责：

- **上方传感器 `extruder_sensor`：** 位于挤出机之前，是 ACE 和挤出机的唯一交接点，也是自动换料必需项。
- **下方传感器 `toolhead_sensor`：** 位于挤出机与喷嘴之间，是可选观测点。默认 `toolhead_sensor_bypass: True`，填写引脚后也只读取显示，不作为换料依据。
- **总五通传感器 `rdm_sensor`：** 单 ACE 可选；多 ACE 自动换料必需，用于确认公共路径已经释放。
- **一级五通传感器 `aceN_hub_sensor`：** 只用于 2 至 4 台 ACE。每个分支可安装传感器，也可使用该分支单独标定的受限盲回退。

每次只配置一路传感器，重启 Klipper 后先用手插入和抽出耗材，确认界面稳定切换。配置对应对象后可执行：

```gcode
QUERY_FILAMENT_SENSOR SENSOR=extruder_sensor
QUERY_FILAMENT_SENSOR SENSOR=toolhead_sensor
QUERY_FILAMENT_SENSOR SENSOR=rdm_sensor
QUERY_FILAMENT_SENSOR SENSOR=ace0_hub_sensor
```

只查询已填写引脚的对象。状态相反时先核对常开、常闭和接线，再决定是否使用 `!`。状态跳变时先修复接头、供电或机械拨片，不要用很大的去抖值掩盖故障。

## 10. 标定路径距离

### 上方传感器到喷嘴

ACE Pro 使用直流送料电机，ACE 命令中的“长度”只是固件参考量，不是可重复的真实位移。装载只有在上方传感器稳定触发时才算到位；`upper_sensor_feed_timeout` 是最终硬停止。

上方传感器触发后，ACE 停止，后续由挤出机步进电机完成。需要在 `ace.cfg` 中标定：

```ini
toolhead_sensor_bypass_load_length: <上方传感器触发点到喷嘴目标位置的实测毫米数>
toolhead_sensor_bypass_calibrated: False
upper_sensor_feed_timeout: 30
```

模板值 `25` 不是通用距离。先保持 `toolhead_sensor_bypass_calibrated: False`，测量方法：

1. 保持 `toolchange_mode: manual` 和 `physical_actions_enabled: False`。
2. 打印机待机，按材料要求安全加热热端。
3. 从打印头上方入口用手送入一段测试耗材，让它停在上方传感器刚刚稳定触发的位置。该距离位于所有 ACE 共用的打印头段，不选择 ACE、设备或槽位。
4. 使用本机已验证的挤出控制，以低速、小步长送到喷嘴目标位置并累计距离。
5. 完整退出耗材后至少重复三次，结果稳定后再填写。

`0` 表示尚未标定，自动换料应保持未就绪。`250 mm` 只是防误填硬上限，不是建议距离。不要通过增大参考距离或超时来掩盖 PTFE 折弯、五通阻力、送料轮打滑或传感器故障。

### 总五通和多 ACE 分支

单 ACE 没有总五通传感器时，需要实测 `toolchange_retract_length` 和 `rdm_clear_move_length`。多 ACE 必须配置总五通传感器，并为每台动作型 ACE 单独标定：

```ini
ace0_hub_retract_length: 0
ace0_hub_clear_move_length: 0
ace1_hub_retract_length: 0
ace1_hub_clear_move_length: 0
```

有一级传感器时，`retract_length` 是寻找传感器释放的最大距离，`clear_move_length` 是释放后的停车余量。没有一级传感器时，两者组成该分支的受限盲回退。不同分支不能互相复制数值。完整方法见[多 ACE](Multi-ACE#每设备分支距离)。

这类分支验证需要指定实际 ACE 通道。手动模式下单独发送 `T0`、`T4` 等工具命令只会被提示并忽略；应在完成第 13 节的动作授权后，通过手动命令的 `TOOL` 参数选择槽位：

```gcode
ACE_FEED TOOL=T0 LENGTH=<短测试参考量> SPEED=<低测试速度>
ACE_RETRACT TOOL=T0 LENGTH=<短测试参考量> SPEED=<低测试速度>
```

例如校准 ACE 2 的一级分支，可选择 `T4-T7` 中一个已装入测试耗材的槽位。一级分支参数属于整台 ACE，而不是某一个槽位；先用一个槽位标定，再用该设备的其他槽位检查路径一致性。Fluidd 中的做法相同：先切换到目标 ACE，再在目标槽位上点击手动送料或回料。

## 11. 可选共享编码器

编码器应安装在总五通之后、上方传感器之前，使全部 ACE 分支经过同一个测量点：

```ini
encoder_sensor_pin: <本机编码器真实脉冲引脚>
encoder_resolution: 0
encoder_detection_length: 20
encoder_min_tracking_ratio: 0.6
encoder_mode: off
encoder_print_mode: off
encoder_print_detection_length: 20
```

新安装先保持两个模式均为 `off`。确认用手移动耗材时脉冲会变化后，在打印机待机、当前工具已卸载、路径为 `empty` 且辅助送料关闭时执行：

```gcode
ACE_ENCODER_CALIBRATE START=1
```

也可以在卡片或独立页点击“开始计数”。编码器校准不选择 ACE 通道，也不接受 `TOOL` 参数。校准的是总五通之后的共享编码器，必须用手推动测试耗材通过编码器；不要启动 ACE、辅助送料或挤出机来代替这一步。推动时观察 Fluidd 控制台：脉冲每次增加都会同步显示本次新增、校准累计和硬件累计，静止时不应继续刷出相同计数。

默认校准分 `3` 段，每段用手准确推动耗材通过编码器 `150 mm`，然后提交该段长度：

```gcode
ACE_ENCODER_CALIBRATE LENGTH=150
```

中途取消：

```gcode
ACE_ENCODER_CALIBRATE CANCEL=1
```

每段独立记录脉冲数和 `mm/脉冲`。三段最大偏差 `<=5%` 时通过，`>5%` 且 `<=10%` 时检查打滑和测量方法并明确确认后才保存，`>10%` 或任一段脉冲不足时拒绝保存。校准不会驱动 ACE 或挤出机，完成或取消后控制台会停止校准计数输出。`150 mm` 只用于校准；运行时 `encoder_detection_length` 与 `encoder_print_detection_length` 继续使用短窗口。完成后先使用 `encoder_mode: monitor` 观察完整装卸；只有脉冲、误报、漏报和故障停止都通过本机验收后，才考虑 `protect`。打印监测同样应先用 `monitor`，最后才考虑 `pause`。

编码器只能证明耗材是否移动，不能判断路径中是否有料，不能替代上方或五通传感器，也不会自动补偿打滑。`encoder_detection_length` 是检测窗口，不是到位距离。

## 12. 配置七个必用宏

自动换料固定需要七个宏：

| 宏 | 作用 | 模板默认状态 |
| --- | --- | --- |
| `_ace_prepare_toolchange` | 保存状态、抬升并移动到换料位置 | 机器动作保持注释 |
| `_ace_cut_filament` | 切断旧耗材 | 机器动作保持注释 |
| `_ace_load_filament_to_toolhead` | 进入 V3 受控送料路径 | 已启用 |
| `_ace_unload_filament_from_toolhead` | 进入 V3 受控回料路径 | 已启用 |
| `_ace_wipe_nozzle` | 调用本机喷嘴清理流程 | 机器动作保持注释 |
| `_ace_restore_after_toolchange` | 恢复高度、状态和打印位置 | 机器动作保持注释 |
| `_ace_pause_on_toolchange_error` | 失败时提示并暂停活动打印 | 已启用 |

V3 不执行尖端成型，因此自动换料必须使用切刀。保持：

```ini
require_path_hooks: True
require_cut_hook: True
```

打开 `ace.cfg` 的“本机物理动作宏样板”区域，逐个修改前处理、切刀、擦嘴和后处理。样板坐标来自特定测试机，默认整段注释是有意的。不要创建空宏骗过预检，也不要直接取消全部注释。

每个机器宏必须检查：

- XYZ 是否已经归零，宏使用绝对还是相对坐标。
- 停车点、切刀点和擦嘴点是否在本机运动范围内。
- 工具头、探针、热床、打印件、机壳和切刀之间是否有足够间隙。
- 切刀进入方向、行程、速度和复位方向是否正确。
- 喷嘴温度是否允许当前材料挤出和回抽。
- 前后处理是否使用相同状态名，Z 抬升和恢复是否安全。
- 已有 `CLEAN_NOZZLE` 等本机宏是否已经单独验收。

> **切刀警告：** 自动换料中的切刀不是可选装饰。未经空机、低速、逐段测试，不得启用 `_ace_cut_filament`；坐标错误可能直接撞击机架、热床或打印件。

宏验收时继续保持手动模式和 ACE 物理动作门禁关闭，先归零机器，再按本机降低后的测试速度逐项执行。`physical_actions_enabled: False` 只阻止驱动发起 ACE 动作，不会阻止用户直接调用 G-code 宏；下面每条宏命令都会执行真实机器动作。

1. 单独执行 `_ACE_PREPARE_TOOLCHANGE`，检查抬升、停车和温度逻辑；随后执行 `_ACE_RESTORE_AFTER_TOOLCHANGE`，确认能够成对恢复。
2. 在没有打印件且切刀区域可观察时执行 `_ACE_CUT_FILAMENT`，检查接近、切入、退出和复位方向。
3. 单独执行 `_ACE_WIPE_NOZZLE`，确认已有清洁宏不会撞击热床、探针或机壳。
4. `_ACE_LOAD_FILAMENT_TO_TOOLHEAD` 和 `_ACE_UNLOAD_FILAMENT_FROM_TOOLHEAD` 是驱动路径入口，不使用它们代替后续的受控装卸验收。
5. `_ACE_PAUSE_ON_TOOLCHANGE_ERROR` 不移动机器；待机时只检查提示和无动作行为。暂停分支应在后续受控的换料故障验收中观察，不要为了测试而在普通打印中直接调用。

前处理成功后必须完成配对的后处理或按本机安全方式恢复状态。任一宏失败时停止，不要继续测试下一项。

不要在任何配置文件中重新定义 `T0-T15` 或 `TR`，这些命令由驱动注册。

## 13. 首次 ACE 物理动作

完成路径和传感器检查后，继续保持：

```ini
[ace]
toolchange_mode: manual
```

只对一台已经确认的 ACE1 修改：

```ini
[ace_device ace0]
physical_actions_enabled: True
```

重启 Klipper 并再次确认打印机待机。先选择可观察、可立即停止的槽位，用低速度和本机选定的短参考量检查方向：

```gcode
ACE_FEED TOOL=T0 LENGTH=<本机短测试参考量> SPEED=<本机低测试速度>
ACE_RETRACT TOOL=T0 LENGTH=<本机短测试参考量> SPEED=<本机低测试速度>
```

尖括号内容必须替换，不能原样发送。`ACE_FEED` 和 `ACE_RETRACT` 是直接的手动设备动作，只用于确认通信、方向和受限参考量，不是完整自动装载闭环，不能证明上方传感器会自动停止本次手动动作。

`TOOL=Tn` 就是通道选择：单台 ACE 使用 `T0-T3`；第二台使用 `T4-T7`，依次扩展。不要先发送单独的 `Tn` 再发送 `ACE_FEED`，因为手动模式会忽略单独的工具命令，真正的目标槽位由 `ACE_FEED` 或 `ACE_RETRACT` 自己的 `TOOL` 参数决定。

每次动作后确认：

- ACE 已经停止，耗材方向正确。
- 没有磨料、折弯、接头松脱或线盘缠绕。
- 传感器状态和耗材实际位置一致。
- 当前路径位置明确，不是 `unknown`。

通信超时或动作结果不明时不要立即重复命令。先确认电机停止并人工检查耗材位置。

## 14. 可选：只使用辅助送料

不准备自动换料时，可以一直保持 `toolchange_mode: manual`，仅使用 ACE 内置辅助送料。目标 ACE1 必须已完成路径验收并设置 `physical_actions_enabled: True`。

待机时启用：

```gcode
ACE_ENABLE_FEED_ASSIST TOOL=T0
```

打印中启用必须明确确认：

```gcode
ACE_ENABLE_FEED_ASSIST TOOL=T0 CONFIRM=1
```

停用：

```gcode
ACE_DISABLE_FEED_ASSIST
```

单打印头全局同时只能有一个辅助送料槽位。辅助送料不会执行 `Tn` 换料，也不能保证多色文件使用正确颜色。

## 15. 启用并验收自动换料

启用自动模式前必须全部满足：

- ACE1 在线并已完成单项物理动作验收。
- 上方传感器稳定，入口到喷嘴距离已经重复标定。
- 单 ACE 总五通停车方案已经验证；多 ACE 的总五通和所有分支清空方案已经验证。
- 七个必用宏均有真实实现，切刀、擦嘴、停车和恢复动作已逐项验收。
- 编码器若使用 `protect`，已经配置、校准并完成监测测试。
- 当前路径状态明确，没有活动辅助送料、编码器校准或其他换料事务。

最后修改：

```ini
[ace]
toolchange_mode: automatic
```

重启 Klipper 后执行：

```gcode
ACE_GET_STATUS
```

检查 `toolchange_mode` 为 `automatic`、`toolchange_ready` 为真，并且 `toolchange_blocked_reason` 为空。常见阻塞原因：

| 阻塞原因 | 处理方向 |
| --- | --- |
| `manual_mode` | 仍处于手动模式 |
| `physical_actions_disabled` | 目标 ACE1 尚未授权物理动作 |
| `machine_hooks_incomplete` | 七个必用宏中有实现缺失 |
| `path_sensors_incomplete` | 上方或当前拓扑所需传感器不完整 |
| `lower_sensor_bypass_uncalibrated` | 上方交接点到喷嘴距离尚未标定 |
| `total_hub_sensor_missing` | 多 ACE 没有总五通传感器 |
| `branch_clearance_incomplete` | 多 ACE 分支回退距离尚未标定 |
| `encoder_not_ready` | 编码器保护模式未校准或存在故障 |

不要通过删除宏绑定、关闭切刀要求、伪造传感器状态或盲目增加距离来消除阻塞。

### 待机状态完整验收

不要直接使用打印任务进行第一次换料。使用显式命令测试，未就绪时该命令会报错而不是静默忽略：

```gcode
ACE_CHANGE_TOOL TOOL=T0
ACE_CHANGE_TOOL TOOL=TR
```

按顺序完成：

1. 从明确的空路径装载 `T0` 到喷嘴。
2. 使用 `TR` 完全卸载，确认路径回到 `empty`。
3. 在同一 ACE 内测试 `T0 -> T1`。
4. 确认上方传感器触发会停止 ACE，超时未触发会中止动作。
5. 确认卸载先由挤出机回抽到上方释放，再由 ACE 清空五通。
6. 多 ACE 用户逐条验证所有分支后，最后才测试例如 `T0 -> T4` 的跨设备换料。

任何传感器矛盾、设备掉线、搜索超限或未知动作结果都必须停止验收并人工检查。

## 16. 配置切片器

V3 不接管 `PRINT_START` 的温度参数。现有开始宏确实声明 `EXTRUDER` 和 `BED` 时，可使用：

```gcode
PRINT_START EXTRUDER=[nozzle_temperature_initial_layer] BED=[bed_temperature_initial_layer_single]
T[initial_tool]
```

切片后打开实际 G-code 检查：

- `T[initial_tool]` 必须展开为单独一行 `T0`、`T1` 等，不能原样保留。
- 工具行位于 `PRINT_START` 后时，会在整个开始宏完成后执行初始换料。
- 如果某个开始动作必须在装载耗材后执行，应在已归零、温度合适且可安全移动的位置重新安排工具指令，不要简单把 `Tn` 移到 `G28` 和加热之前。
- 单 ACE 只能使用 `T0-T3`，两台 ACE 才能使用 `T4-T7`。

手动模式或自动换料未就绪时，切片中的 `Tn` 会提示后被忽略，打印不会暂停。因此开始多色打印前必须确认 `toolchange_ready: true`。

## 17. 首次打印

建议按以下顺序进行：

1. **短单色打印：** 使用已验证槽位，观察 ACE、传感器、PTFE 和编码器状态。
2. **待机换料复测：** 打印后再次完成 `T0 -> TR -> T0`，确认热态和冷态差异可控。
3. **短双色打印：** 先在同一 ACE 内使用两个已验证槽位，选择耗材少、换色次数少的测试件。
4. **故障恢复：** 确认换料失败时会暂停并保留明确现场，人工处理后不会把未知路径当成成功。
5. **多 ACE 打印：** 只有逐分支完成真机验收后才可测试，首次测试不得无人值守。

首次打印期间不要离开机器。发现异常声响、磨料、PTFE 弯折、接头松脱、切刀卡住或线盘缠绕时立即停止。

## 18. 日常检查、升级和排障

每次多色打印前检查：

- ACE 在线，目标槽有料，材料和颜色与切片一致。
- 当前工具、路径状态和传感器状态与实物一致。
- `toolchange_ready` 为真，`toolchange_blocked_reason` 为空。
- 没有正在进行的辅助送料、校准或残留换料事务。

常用只读命令：

```gcode
ACE_GET_STATUS
ACE_REFRESH DEVICE=ace0
ACE_RECONNECT DEVICE=ace0
ACE_ENCODER_STATUS
```

常见现象：

| 现象 | 含义 |
| --- | --- |
| “自动换料未配置，已忽略 T0” | 手动模式或自动换料未就绪；单色可继续，多色会使用错误颜色 |
| “Upper filament sensor did not trigger...” | 总送料超时内上方传感器未稳定触发；先查传感器、路径和送料轮 |
| 传感器显示“未配置” | 相应引脚为空或对象未创建；未安装时属于正常状态 |
| 下方传感器偶尔不触发 | 默认旁路时只影响显示；修好前不要让它参与闭环 |
| 编码器没有脉冲 | 不等于无料；检查引脚、压轮和耗材是否实际经过编码轮 |
| ACE 在线但按钮不可用 | 仍可能被打印状态、设备门禁、槽位、路径锁或自动换料预检阻止 |

升级、重装或增删 ACE 时，先备份并确认打印机待机，然后使用新版本源码重新运行安装器。先加 `--dry-run`，确认最终完整设备列表和顺序，再正式执行。安装器不会自动重启服务或执行动作。

卸载：

```bash
cd ~/ace-pro-control-center
./installer/uninstall.sh
```

详细错误处理见[故障排查](Troubleshooting)，全部配置项见[配置说明](Configuration)，命令列表见[命令与 API](Commands-and-API)。

## 完成检查表

- [ ] 安装前备份和安装器持久快照均可恢复，恢复命令与校验结果已记录，安装和重启均在待机状态完成。
- [ ] ACE 数量、型号、稳定串口、顺序和工具号与实物一致。
- [ ] 在 `manual` 和 `physical_actions_enabled: False` 下完成只读验收。
- [ ] 上方传感器及当前拓扑所需五通方案已验证。
- [ ] 上方传感器到喷嘴的挤出机距离经过至少三次测量。
- [ ] 编码器如启用保护，已经完成默认 `150 mm x 3` 校准、`5%/10%` 一致性检查、短窗口监测和故障测试。
- [ ] 七个必用宏均有真实实现，切刀和所有机器坐标来自本机。
- [ ] 只授权一台 ACE1 完成短动作，再完成待机装载、卸载和同设备换料。
- [ ] 自动模式下 `toolchange_ready` 为真，阻塞原因为空。
- [ ] 切片后的初始工具号已正确展开，没有超出已安装工具范围。
- [ ] 先完成短单色和短双色测试，再进行长时间或多 ACE 打印。

更换主板、工具板、工具头、切刀、传感器、PTFE 路径或 ACE 顺序后，受影响的项目必须重新验收。
