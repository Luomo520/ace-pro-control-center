# ACEPROSV08 独立网页与 Fluidd 卡片设计

## 1. 目标

创建 GitHub 仓库 `Luomo520/fluidd-acepro-card-ACEPROSV08`，为
`szkrisz/ACEPROSV08` 驱动提供中文独立控制网页和 Fluidd 仪表盘卡片。
两个界面使用同一套 Moonraker API、状态定义、命令权限和功能范围，区别仅为
容器宽度与排版密度。

第一版仅支持一台 ACE Pro 和四个料槽。项目不修改用户的 `printer.cfg`、
`ace.cfg`、传感器引脚或自定义宏，也不兼容 `Kobra-S1/ACEPRO` 驱动。

## 2. 上游和许可证

项目来源如下：

- 驱动和 G-code：`szkrisz/ACEPROSV08`，基线提交 `0311eb3`。
- 独立网页和料卷视觉参考：`Kobra-S1/ACEPRO`。
- Fluidd 集成：`fluidd-core/fluidd`，首版验证版本 `v1.37.2`。
- 旧卡片宽度和安装经验：`Luomo520/fluidd-acepro-card`。

上述代码均使用 GPL-3.0，目标仓库继续使用 GPL-3.0，并保留完整
`LICENSE`。仓库增加 `THIRD_PARTY_NOTICES.md`，列出来源、作者、链接、上游
版本及修改范围。保留继承文件中的版权声明，不把参考项目的代码声明为原创。
仓库同时提供可重建 Fluidd 定制产物的源码、补丁和构建说明，不能只发布压缩
后的前端文件。

## 3. 系统边界

系统由四个边界清晰的部分组成：

1. ACEPROSV08 驱动提供硬件状态和 G-code。对驱动的改动只增加
   `connected`、`feed_assist_index` 和 `max_dryer_temperature` 三个只读状态，
   不改变现有送料和换料逻辑。
2. Moonraker `ace_status` 组件负责读取 Klipper 对象、合并库存和传感器状态、
   校验命令并暴露稳定 API。
3. 独立网页通过 `/ace.html` 使用该 API，不直接拼接或发送 G-code。
4. Fluidd 卡片使用同一 API。Fluidd v1.37.2 与独立网页的 Vue 运行时不同，
   因此不强行共享 Vue 组件源码，而是共享 schema、命令客户端、状态文案和契约
   测试，以保证功能一致。

网页和卡片不得绕过 Moonraker 组件调用 `/printer/gcode/script`。

## 4. 状态来源与优先级

Moonraker 每次读取以下 Klipper 对象：

- `ace`
- `save_variables`
- `filament_switch_sensor extruder_sensor`
- `filament_switch_sensor toolhead_sensor`
- `print_stats`
- `idle_timeout`

字段来源固定如下：

- 连接、ACE 状态、温度、风扇和烘干状态来自 `ace`。
- 库存来自 `save_variables.variables.ace_inventory`。缺失或格式错误时退回
  `ace.slots`，同时返回非阻断警告。
- 当前工具来自 `save_variables.variables.ace_current_index`，合法值为 `-1..3`。
- 无限续料来自 `ace.endless_spool`。
- 辅助送料槽来自 `ace.feed_assist_index`，合法值为 `-1..3`。
- 烘干温度上限来自 `ace.max_dryer_temperature`。
- 上方传感器对应 `extruder_sensor`，下方传感器对应 `toolhead_sensor`。
- 打印限制由 `print_stats.state` 和 `idle_timeout.state` 共同判断。

任何对象缺失都必须生成稳定的默认结构，不能让前端因字段缺失而崩溃。缓存只
用于短暂 Klipper 重连，响应必须标注 `stale: true`；缓存不能把断线状态伪装成
在线。

## 5. Moonraker API

保留四个固定端点：

### 5.1 `GET /server/ace/status`

```json
{
  "api_version": 1,
  "driver": "ACEPROSV08",
  "connected": true,
  "status": "ready",
  "busy": false,
  "stale": false,
  "current_tool": 0,
  "temperature": 42.6,
  "fan_speed": 7000,
  "feed_assist_index": -1,
  "dryer": {
    "active": false,
    "status": "stop",
    "target_temperature": 0,
    "duration_minutes": 0,
    "remaining_minutes": 0
  },
  "sensors": {
    "upper": {"name": "extruder_sensor", "available": true, "detected": true},
    "lower": {"name": "toolhead_sensor", "available": true, "detected": true}
  },
  "endless_spool": {
    "enabled": false,
    "runout_detected": false,
    "in_progress": false
  },
  "printing": false,
  "warnings": []
}
```

### 5.2 `GET /server/ace/slots`

固定返回四个按 `index` 排序的料槽：

```json
{
  "api_version": 1,
  "slots": [
    {
      "index": 0,
      "status": "ready",
      "material": "PLA",
      "color": {"rgb": [226, 58, 67], "hex": "#E23A43"},
      "temperature": 210,
      "loaded": true,
      "active": true
    }
  ],
  "warnings": []
}
```

空槽仍返回完整字段，材料为空字符串、颜色为黑色、温度为 `0`。

### 5.3 `GET /server/ace/capabilities`

返回 API 版本、驱动名称、单设备限制、四槽限制、传感器可用性、烘干温度上限、
支持命令和参数范围。前端以此决定控件是否显示为可用状态，但不能据此绕过服务端
校验。

### 5.4 `POST /server/ace/command`

请求使用确切的 ACEPROSV08 G-code 名称：

```json
{
  "command": "ACE_SET_SLOT",
  "params": {
    "INDEX": 0,
    "COLOR": [226, 58, 67],
    "MATERIAL": "PLA",
    "TEMP": 210
  }
}
```

成功响应包含 `success`、`command` 和服务端生成的 `request_id`。失败响应使用：

```json
{
  "success": false,
  "error": {
    "code": "invalid_parameter",
    "message": "料槽索引必须在 0 到 3 之间",
    "field": "params.INDEX"
  }
}
```

不得在响应中返回含敏感路径的 Python traceback。

参数或请求格式错误返回 HTTP `400`，打印状态冲突或设备忙碌返回 `409`，驱动未
连接返回 `503`，未处理的服务端错误返回 `500`。正常的离线状态读取仍返回 `200`
和 `connected: false`，便于界面显示诊断信息。

## 6. 命令白名单

允许的命令和参数如下：

| 命令 | 参数 | 服务端限制 |
| --- | --- | --- |
| `ACE_SET_SLOT` | `INDEX`, `EMPTY` 或 `COLOR`, `MATERIAL`, `TEMP` | `INDEX=0..3`；RGB 每项 `0..255`；材料匹配 `[A-Za-z0-9._+-]{1,24}`；温度 `1..500` |
| `ACE_CHANGE_TOOL` | `TOOL` | `-1..3` |
| `ACE_CHANGE_SPOOL` | `INDEX` | `0..3` |
| `ACE_FEED` | `INDEX`, `LENGTH`, `SPEED` | 索引 `0..3`；单次长度 `1..500mm`；速度 `1..120mm/s` |
| `ACE_RETRACT` | `INDEX`, `LENGTH`, `SPEED` | 与 `ACE_FEED` 相同 |
| `ACE_ENABLE_FEED_ASSIST` | `INDEX` | `0..3` |
| `ACE_DISABLE_FEED_ASSIST` | `INDEX` | `0..3` |
| `ACE_START_DRYING` | `TEMP`, `DURATION` | 温度 `1..max_dryer_temperature`；时长 `1..1440` 分钟 |
| `ACE_STOP_DRYING` | 无 | 始终允许 |
| `ACE_ENABLE_ENDLESS_SPOOL` | 无 | 非忙碌时允许 |
| `ACE_DISABLE_ENDLESS_SPOOL` | 无 | 始终允许 |
| `ACE_SAVE_INVENTORY` | 无 | 非忙碌时允许 |
| `ACE_QUERY_SLOTS` | 无 | 始终允许 |

旧卡片中 `ACE_SET_SLOT T=...` 的写法必须删除，ACEPROSV08 只使用
`INDEX=...`。服务端拒绝未知命令、未知参数、重复参数、换行、控制字符和超出范围
的值。参数由映射器生成 G-code，不允许直接拼接客户端字符串。

打印期间禁止换料、卸载、手动送料/回抽、编辑库存和开启辅助送料。读取状态、查询
库存、停止烘干和关闭无限续料仍可执行。危险操作需要前端二次确认，服务端仍独立
执行打印状态检查以防绕过。

## 7. 界面功能

独立网页和 Fluidd 卡片都包含：

- 在线、忙碌、当前工具、温度和错误状态。
- 上方和下方传感器的开关式状态，以及
  `ACE -> 上方 -> 挤出机 -> 下方 -> 喷嘴` 路径。
- 烘干目标温度、时长、开始、停止和剩余时间。
- 四个料槽的状态、材料、颜色、温度、装载、卸载、辅助送料、编辑和置空。
- 手动送料、手动回抽、无限续料、诊断和错误显示。
- 离线、忙碌、打印中限制、确认对话框和中文错误说明。

材料使用带常用项目的下拉框，并允许符合白名单的自定义 ASCII 材料标识。颜色使用
颜色选择器、色块和十六进制输入，保存成功后重新读取 `/slots`，以服务端持久化结果
为准，不能用轮询状态覆盖正在编辑的表单。

料卷采用 Kobra-S1 原始几何：后挡板、彩色卷身、前挡板和中心孔，不增加遮罩。
空槽降低饱和度但仍保持可辨识轮廓。

## 8. Fluidd 卡片布局

卡片遵循旧项目的 Fluidd 栅格：`cols=12`、`md=6`、桌面根据仪表盘列数计算
`lg`。在 1366px Fluidd 双栏仪表盘中，卡片内容宽约 632px。

桌面半栏布局固定为：

- 顶部一行设备、双传感器路径和烘干控制。
- 四个耗材卡片在同一行，每槽约 151px。
- 每个料槽的横向料卷居中，材料信息在下方，四个操作按钮为 `2x2`。
- 无限续料、手动送料/回抽、诊断与错误压缩为底部单行工具栏。

移动端低于断点时四槽变为 `2x2`，更窄时变为单列。任何断点不得产生水平滚动、
文字重叠或按钮高度变化。独立网页可使用更宽间距，但不能增加或删除功能。

## 9. 安装、更新和恢复

安装入口为 `ui-installer.sh`，使用 Bash 字符菜单，不依赖 `dialog`、`whiptail`、
Node.js 或桌面环境。顶部显示驱动版本、Moonraker API、Fluidd 版本、面板版本、
安装状态和最近备份时间。

菜单固定为：

```text
1. 安装 / 更新 ACE Pro 界面
2. 强制安装（跳过驱动和 API 检测）
3. 卸载界面并恢复安装前版本
4. 检查安装状态
5. 退出
```

普通安装在写入前检测 ACEPROSV08 文件、`[ace]` 配置、Moonraker、Fluidd 和
API。强制安装只跳过驱动与 API 可用性检测，不跳过目标路径、权限、磁盘空间、
备份、校验、冲突保护和回滚。

### 9.1 备份事务

任何写入、替换、软链接调整或配置修改之前，先创建：

```text
~/.local/share/aceprosv08-ui/backups/YYYYMMDD-HHMMSS/
```

备份 Fluidd 目录、Moonraker `ace_status.py`、`moonraker.conf`、已有独立网页和
安装器将要修改的其他文件。清单记录原始绝对路径、文件类型、软链接目标、SHA-256、
备份路径、项目版本和时间。先校验备份，再开始安装。备份失败或校验不一致时，普通
安装和强制安装都必须停止。

首次安装备份作为卸载基线永久保留。每次更新另建更新前备份。部署先写入同文件系统
的暂存目录并验证，再通过重命名切换。失败时恢复本次备份。被替换和卸载的目录移动到
备份区，不使用 `rm -rf`、`git reset --hard` 或强制覆盖未知文件。

卸载恢复首次安装前状态。如果安装后文件被用户修改，先把当前版本另存为冲突备份，
再提示是否恢复；非交互模式默认停止而不是覆盖。安装器只移除自己记录的配置块和文件。

### 9.2 Git 安装

发布不提供安装压缩包。教程使用：

```bash
git clone --depth 1 https://github.com/Luomo520/fluidd-acepro-card-ACEPROSV08.git
cd fluidd-acepro-card-ACEPROSV08
bash ui-installer.sh
```

更新使用 `git pull --ff-only` 后重新运行安装器。安装器不替用户执行破坏性 Git 操作。
Fluidd 定制产物随 Git 仓库提供，打印机端不需要 Node.js 构建。

服务重启前显示将重启的服务并请求确认。只有 Moonraker 组件变化时需要重启
Moonraker；只有驱动只读状态补丁变化时才提示重启 Klipper。健康检查验证四个 API、
`/ace.html` 和 Fluidd 安装标记，失败自动回滚。

## 10. 测试

### 10.1 Moonraker

- 状态归一化、库存回退、传感器缺失、断线缓存和格式错误测试。
- 每个白名单命令的成功、边界、未知参数、控制字符和打印中限制测试。
- 验证前端无法发送任意 G-code。

### 10.2 安装器

使用临时 HOME 和伪造服务目录测试，不在测试中修改真实打印机：

- 首次安装、重复安装、更新和普通卸载。
- 强制安装确实只跳过驱动/API 检测。
- 任何实际写入前都存在已校验备份。
- 备份失败、暂存失败、健康检查失败和自动回滚。
- 用户修改冲突、软链接恢复和不存在文件的恢复。

### 10.3 前端

- Fluidd v1.37.2 完整构建。
- 两个界面对相同模拟响应产生相同状态和可用操作。
- 颜色和材料保存后刷新仍保持，轮询不能覆盖编辑中的值。
- 离线、忙碌、打印中、空槽、烘干和双传感器组合状态。
- 1366px、1920px、平板和手机视口截图与溢出检查。
- 1366px 半栏宽度约 632px，桌面四槽同一行，每槽无内部溢出。

### 10.4 真机

本地测试全部通过后才允许真机部署。部署前重新备份，先验证只读状态，再验证库存
保存，最后由用户确认是否执行烘干、送料、回抽或换料。禁止自动执行危险硬件动作。

## 11. 发布

首个版本为 `v0.1.0`。README 和 Release 顶部必须显示兼容矩阵：

- 驱动：`szkrisz/ACEPROSV08`，基线 `0311eb3`，以及本仓库声明的兼容版本。
- 不兼容：`Kobra-S1/ACEPRO`。
- Fluidd：已验证 `v1.37.2`。
- 设备：单 ACE、四槽。
- 语言：中文。

README 包含安装、强制安装风险、更新、卸载恢复、故障排查、手动安装和许可证说明。
更新日志记录 API、驱动兼容性、Fluidd 兼容性和迁移注意事项。

实现完成并在 Fluidd v1.37.2 真实构建中验证后，截取实际约 632px 半栏卡片，保存为
`docs/images/fluidd-acepro-card.png`，在 README 和 v0.1.0 Release 中展示。该图片
必须来自实际构建，不得使用设计稿冒充成品；截图不得包含 IP、用户名、路径或其他
私人信息。

## 12. 不在第一版范围

- 多 ACE 设备。
- RFID 管理和 Spoolman 同步。
- 自动修改打印机引脚和传感器配置。
- 替换 ACEPROSV08 的换料、切刀或送料算法。
- 支持 Kobra-S1/ACEPRO、AFC 或通用 MMU 驱动。
- 从网页执行任意 G-code。

## 13. 完成标准

满足以下条件才可发布：

1. 四个 API、命令白名单和错误结构通过自动测试。
2. 普通安装和强制安装都在任何写入前完成可验证备份。
3. 更新失败可自动回滚，卸载可恢复首次安装前状态。
4. 独立网页和 Fluidd 卡片功能一致，库存保存后刷新不丢失。
5. Fluidd v1.37.2 构建通过，桌面半栏四槽横排且无溢出。
6. README、教程、更新日志、许可证、第三方声明和实际卡片图片齐全。
7. 真机部署和危险硬件动作均在用户确认后执行。
