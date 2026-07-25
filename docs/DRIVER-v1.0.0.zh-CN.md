# ACEPROSV08 增强驱动 v1.0.0 更新与调校

## 更新目标

本版针对 DIY Klipper 多色打印中最常见的四类问题：长管送料慢、齿轮打滑后误报、双传感器阶段不清楚、USB 短暂断联后动作状态不确定。

## 耗材路径

```text
送料：ACE T0-T3 -> 公共管路 -> 上方传感器 -> 挤出机 -> 下方传感器 -> 喷嘴
回收：喷嘴 <- 下方传感器 <- 挤出机 <- 上方传感器 <- 公共管路 <- ACE
```

上方传感器触发只代表耗材到达挤出机入口，不代表耗材已经穿过挤出机。驱动会在该阶段切换到工具头挤出机送料，并以更小步长寻找下方传感器。

## 送料配置

| 参数 | 默认值 | 作用 |
| --- | ---: | --- |
| `intermittent_feed` | False | False 连续送料；True 分段送料 |
| `feed_fast_speed` | 160 | 长管快速送料速度，单位 mm/s |
| `feed_approach_length` | 200 | 断续模式下，最后 200 mm 进入慢速阶段 |
| `feed_approach_speed` | 25 | 接近上方传感器的速度 |
| `feed_fast_chunk_length` | 1000 | 断续模式的快速请求分段长度 |
| `feed_slip_compensation_length` | 400 | 传感器未触发时允许的最大补偿 |
| `feed_slip_compensation_chunk` | 50 | 断续模式的每次补偿距离 |
| `feed_slip_compensation_speed` | 25 | 补偿送料速度 |
| `ace_stop_ready_timeout` | 25 | 停止送料后等待 ACE 恢复 ready 的最短时间 |

连续模式下，主路径只发送一条完整距离请求，驱动在执行期间持续监测上方传感器；主路径结束仍未触发时，只再发送一次完整的有限低速补偿。连续模式不会在最后 200 mm 切换速度，因此没有请求切换造成的停顿。

上方传感器触发后，驱动先发送停止送料，再按 `max(ace_stop_ready_timeout, 当前请求距离/速度 + 3 秒)` 等待 ACE 恢复 `ready`。普通命令仍使用 `ace_ready_timeout`，两类超时互不混用。

断续模式下，驱动按 `feed_fast_chunk_length` 快速送料，最后 `feed_approach_length` 按 `ace_motion_chunk_length` 慢速送料，并按 `feed_slip_compensation_chunk` 分段补偿。它更保守，但每个请求结束后都要等待 ACE 回到 `ready`，会产生可见停顿。

调校原则：先准确测量 `toolchange_load_length`，再给少量打滑余量。若总是用完 400 mm 补偿才触发，应检查压料轮、耗材阻力和管路，而不是继续放大补偿上限。

## 工具头送料配置

| 参数 | 默认值 | 作用 |
| --- | ---: | --- |
| `toolhead_feed_fast_speed` | 8 | 上方触发后的初段挤出机速度 |
| `toolhead_feed_fast_length` | 10 | 初段总距离 |
| `toolhead_feed_fast_step` | 5 | 初段每次移动距离 |
| `toolhead_feed_slow_speed` | 5 | 寻找下方传感器的速度 |
| `toolhead_feed_slow_step` | 1 | 慢速检查步长 |
| `toolhead_sensor_max_feed_length` | 200 | 下方传感器未触发时的最大送料上限 |
| `toolhead_sensor_to_nozzle` | 需实测 | 下方传感器到喷嘴的最终送料距离 |

## 回收配置

| 参数 | 默认值 | 作用 |
| --- | ---: | --- |
| `intermittent_retract` | False | False 两阶段连续回抽；True 固定距离分段回抽 |
| `retract_fast_speed` | 120 | 长距离快速回收速度 |
| `retract_parking_length` | 200 | 回收最后 200 mm 降速 |
| `retract_parking_speed` | 25 | 停放前慢速 |
| `toolchange_retract_length` | 需实测 | 完整释放公共通道所需总距离 |

`intermittent_retract: False` 时，驱动把总距离拆成一个快速段和最后一个慢速停放段。例如总长 `1200 mm`、停放段 `200 mm` 时，只执行 `1000 mm @ 120 mm/s` 和 `200 mm @ 25 mm/s` 两个请求。设置为 `True` 后，两个阶段继续按 `ace_motion_chunk_length` 分段，兼容需要频繁释放电机压力的设备。

## 失败行为

- 送料达到上限而目标传感器未触发：执行 `PAUSE`，不执行 `CANCEL_PRINT`。
- 错误信息包含换料方向、失败阶段、已移动距离和上下传感器状态。
- 断联恢复只进行有限次数的状态协调，不无限重放整段送料或回抽。
- 自动恢复仍以传感器状态为依据；机械卡料、错线或切刀失败无法由软件安全猜测。

## 换料与切刀

从已装载工具切换到其他工具时，正确顺序应为：

```text
TA -> TB 开始
换色前准备 -> 到切刀位置 -> CUT_TIP -> 工具头回抽
ACE 回收旧料 -> ACE 送料新料 -> 上方触发
挤出机送料 -> 下方触发 -> 送到喷嘴 -> 换色后处理 -> 完成
```

`CUT_TIP` 和 `_ACE_PRE_TOOLCHANGE` 坐标完全取决于打印机结构。发布模板中的坐标只用于展示配置格式，必须按本机重新标定。

## 发布前测试建议

1. Python 编译和 Klipper 配置解析。
2. 上下传感器静态状态。
3. 20-50 mm 短距离送料与回抽。
4. 无耗材切刀坐标检查。
5. 单次完整换料。
6. 暂停状态下模拟送料失败，确认任务保持暂停而非取消。
7. 最后再测试无限续料与断联恢复。
