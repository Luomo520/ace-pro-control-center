# ACEPROSV08 驱动 v1.1.0 更新说明

本版本为单台 ACE Pro、四料槽的自动跟随打印烘干版本，只适配 `szkrisz/ACEPROSV08`，不兼容 `Kobra-S1/ACEPRO`。

## 自动烘干规则

| 已装载材料 | 自动温度 |
| --- | ---: |
| 全部 PLA | 45°C |
| PLA 与其他材料混装 | 50°C |
| 存在未知材料 | 45°C |
| 全部为 ABS、ABSCF、PETG、PAHTCF、PETCF、PEEK | 60°C |
| 所有槽位为空 | 不启动；运行中则停止 |

最终温度始终取材料规则和 `max_dryer_temperature` 中的较小值。旧配置没有把上限设置为 60°C 以上时，驱动不会越过用户配置。

## 生命周期

- 连续两次读取到 `print_stats.state=printing` 后建立自动任务。
- `paused` 保持当前自动烘干，不影响暂停和恢复打印。
- `complete`、`cancelled`、`error`、`standby` 只停止驱动自动启动的烘干。
- 打印中材料变化可以自动降温，但不会自动升温。
- 1440 分钟任务自然结束且打印仍在继续时，按本次温度上限续期。
- 打印中手动停止后，本次打印不再自动启动。
- 手动启动的烘干不被自动功能接管或停止。

## 断联与错误处理

- ACE 断联和烘干启动失败不会暂停或取消打印。
- 启动和停止请求失败后等待 30 秒再重试，最多三次。
- USB 断联造成的待处理请求会被识别并清理，不会永久卡住状态机。
- 打印结束时若启动响应仍未返回，响应成功后立即补发停止。
- 停止失败时保留自动任务所有权，避免界面错误显示为已经停止。

## 控制命令

```text
ACE_ENABLE_AUTO_DRYING
ACE_DISABLE_AUTO_DRYING
```

两个命令不接受参数，设置通过 `SAVE_VARIABLE` 保存。Fluidd 卡片和 `/ace.html` 均通过 Moonraker 白名单调用，不允许执行任意 G-code。

## 距离标定与五通预停放

`bowden_tube_length` 表示 ACE 出料口到五通进料口的实际 PTFE 管路长度。五通附近允许少量测量误差，因为普通换料到挤出机入口时仍由上方传感器确认；该参数不是 ACE 内部停放点到挤出机的总长度。

开始前打印机必须待机、ACE 必须连接并处于就绪状态，而且上下传感器必须均无料。Fluidd 卡片和 `/ace.html` 提供相同按钮，所有会移动耗材的命令都要在当次弹窗中确认：

```text
ACE_CALIBRATE_FEED INDEX=n CONFIRM=1
ACE_CALIBRATE_RETRACT CONFIRM=1
ACE_CALIBRATION_SAVE CONFIRM=1
ACE_CALIBRATION_CANCEL
```

送料标定使用小分段寻找上方传感器并保存触发距离范围；回料标定记录传感器解除范围，再回收到五通支路估算停放点。完成两步后才允许保存。`preload_parked_estimated` 表示估算停放位置，不是毫米级绝对位置。

修改 `bowden_tube_length`、`five_way_parking_margin` 或标定数据格式会使旧结果过期。标定过期、失败或槽位位置未知时，普通 T0-T3 始终送入喷嘴，并使用完整的传感器保护送料，不依赖估算停放状态。

## 冷态预装载与完全卸载

```text
ACE_PRELOAD INDEX=n CONFIRM=1
ACE_FULL_UNLOAD INDEX=n CONFIRM=1
ACE_ABORT_TOOLCHANGE
```

`ACE_PRELOAD` 仅用于待机维护：不加热、不归零、不移动 XY/Z、不执行切刀，也不追加下方传感器到喷嘴的距离。它在上方传感器触发后联动挤出机，直到下方传感器确认有料。`ACE_FULL_UNLOAD` 把指定槽位完全退回 ACE；紧急停止只终止当前动作，不会把未知位置伪装为安全状态。

升级时旧版位置状态只迁移当前唯一可确认的槽位，其他槽位保存为 `unknown`。遇到失败应先查看上下传感器和槽位位置标签，再决定重新预装载、完全卸载或重新标定，不要用手工修改保存变量掩盖实际位置。

## 安装与回滚

安装器默认同时安装驱动、Moonraker 组件和 Fluidd 卡片，也提供仅驱动、仅卡片和强制安装。安装前会校验完整 SHA-256 清单并建立 `old/` 归档；出现问题可运行：

```bash
sh ui-installer.sh --rollback-latest
```

安装和重启服务前必须确认 `print_stats` 不处于 `printing` 或 `paused`。

Fluidd v1.37.2 是完整测试版本。较低、较高或无法识别的版本由安装器提示兼容风险，用户可取消安装；继续安装时仍保留安装前归档和最近一次回滚来源。
