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

## 安装与回滚

安装器默认同时安装驱动、Moonraker 组件和 Fluidd 卡片，也提供仅驱动、仅卡片和强制安装。安装前会校验完整 SHA-256 清单并建立 `old/` 归档；出现问题可运行：

```bash
sh ui-installer.sh --rollback-latest
```

安装和重启服务前必须确认 `print_stats` 不处于 `printing` 或 `paused`。
