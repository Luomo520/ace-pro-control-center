# Ace Pro Control Center | ACE Pro 管理中心：兼容性说明

## 1. 兼容原则

Klipper 通常使用 Git 提交而不是稳定语义版本号，厂商固件也经常保留版本号但修改内部实现。因此 V3 不按日期或版本字符串盲目放行，而是在安装前检查实际目录、Python 运行环境和必需 API。Fluidd 源码集成同时检查版本范围和源码能力锚点；版本号匹配但源码结构不匹配时仍拒绝修改。

安装器始终先安装不依赖 Fluidd 源码的 `/ace-v3/` 独立页面。原生 Dashboard 卡片属于额外集成层，兼容性不足时不得影响 Klipper 驱动和独立页面安装。

## 2. Klipper

### 2.1 支持条件

- Klipper 实际运行 Python 为 `>=3.8`；发布源码同时通过 Python `3.8.10` 编译检查。
- Klipper Python 可导入 `pyserial >= 3.4`；上游 Klipper 固定的 `pyserial 3.4` 属于支持范围。
- 源码树提供 V3 使用的配置节、G-code、Reactor、对象注册和事件 API。
- `klippy/extras` 可写并支持 Python package extra。
- 单个安装任务对应一个明确的 Klipper checkout 和配置目录。

安装器会显示 Git 提交或可读取的版本标识，但版本标识只用于诊断，能力探测结果才决定是否继续。

### 2.2 目录布局

安装器自动依次查找：

| 内容 | 自动候选 |
| --- | --- |
| Klipper | `~/klipper`、`~/klipper-master`、`/opt/klipper`、`/usr/share/klipper` |
| Moonraker | `~/moonraker`、`~/moonraker-master`、`/opt/moonraker`、`/usr/share/moonraker` |
| 配置目录 | `~/printer_data/config`、`~/klipper_config`、包含 `printer.cfg` 的用户主目录 |
| Fluidd 静态目录 | `~/fluidd`、`/usr/share/fluidd`、`/var/www/fluidd` |
| Klipper Python | `~/klippy-env/bin/python`、`~/klipper-env/bin/python`、checkout 同级虚拟环境、`/usr/bin/python3` |

厂商固件或多实例环境应显式传入 `--klipper-home`、`--moonraker-home`、`--config-dir`、`--fluidd-home` 和 `--klipper-python`，不得依赖自动选择。相同 Klipper checkout 被多个打印机实例共享时，不应由不同实例分别自动卸载共享 extra。

### 2.3 不支持或失败关闭

- Python `3.7` 及更早版本。
- 缺少 `pyserial` 的 Klipper 运行环境。
- 厂商删除或改写必需 Klipper API。
- 只读 Klipper extras 目录。
- 无法唯一确认 checkout、配置目录或运行 Python 的多实例环境。

安装器不自动修改虚拟环境。缺少依赖时先停止，并显示应使用的 Klipper Python；用户确认环境后再安装，避免不可回滚的隐式 `pip` 修改。

### 2.4 已验证 Klipper 基线

以下上游源码已经通过同一套源码 API 探测：

| Klipper | 结果 |
| --- | --- |
| `v0.10.0` | 通过 |
| `v0.11.0` | 通过 |
| `v0.12.0` | 通过 |
| `v0.13.0` | 通过 |
| 当前上游提交 `d865997` | 通过 |

这些结果用于证明探测器覆盖不同代际，不构成按版本号直接放行。厂商分支即使报告相同版本，仍要满足当前源码 API、Python 和 pyserial 条件。

### 2.5 可选共享编码器

共享编码器依赖 Klipper 的 `pulse_counter.MCU_counter` 和可用于脉冲计数的真实 MCU 引脚。打印连续监测还需要活动挤出机可通过 `find_past_position()` 按 MCU 预计打印时间读取物理位置。未安装编码器时保持 `encoder_sensor_pin` 为空，并将 `encoder_mode`、`encoder_print_mode` 保持为 `off`，不增加 Klipper 启动要求。有值时驱动以固定内部名称创建编码器对象；旧 `encoder_sensor_name` 只作兼容。厂商分支缺少打印位置接口时只使打印监测不可用，不影响 ACE 状态和普通打印。

兼容性探测通过只说明接口存在，不代表真实编码器已经收到脉冲。仍需在打印机待机时完成 `ACE_ENCODER_STATUS`、默认 `150 mm x 3` 人工校准和取消测试，先分别使用 ACE 动作与打印 `monitor` 观测；这些步骤通过前保持 `protect`、打印 `pause` 关闭。

## 3. Fluidd

### 3.1 三种模式

| 模式 | 行为 |
| --- | --- |
| `auto` | 默认。源码兼容时安装原生卡片；不兼容时只保留 `/ace-v3/` 独立页面 |
| `source` | 强制原生源码集成；版本或能力不匹配时安装前失败 |
| `standalone` | 不修改 Fluidd 源码，只安装独立页面 |

### 3.2 原生源码卡片范围

首批支持官方 Fluidd `1.34.x-1.37.x`：

| Fluidd | 源码 profile | 状态 |
| --- | --- | --- |
| `1.34.x-1.35.x` | `mmu` | 支持 |
| `1.36.x` | `afc` | 支持 |
| `1.37.x` | `sortable-afc` | 支持，主生产构建基线为 `1.37.3` |
| `1.33.x` 及更早 | 无 | `auto` 回退独立页面，`source` 拒绝 |
| `1.38.x` 及以后 | 未确认 | 在新增真实源码构建测试前失败关闭 |

版本范围只是第一道检查。Dashboard 组件注册、布局、路由、侧栏和原生工具命令区锚点必须同时唯一匹配；存在 V2/V3 之外的 `/acepro` 冲突时不会覆盖用户源码。工具命令区补丁只在有效 `ace.device_count` 存在时按每台四槽过滤并分行，无法确认 ACE 状态时保持上游 Fluidd 行为。

源码补丁完成后仍需使用该 Fluidd 版本自身声明的 Node 和包管理器版本执行构建。安装器不会替用户升级 Node、替换整个 Fluidd 目录或自动重启服务。

### 3.3 已验证 Fluidd 基线

| 官方 Fluidd | 能力探测 | TypeScript 检查 | 生产构建 |
| --- | --- | --- | --- |
| `1.34.4` | 通过 | 通过 | Windows 上触发上游未修改源码同样存在的 Vite checker `TS5042` |
| `1.35.1` | 通过 | 通过 | Windows 上触发上游未修改源码同样存在的 Vite checker `TS5042` |
| `1.36.4` | 通过 | 通过 | Windows 上触发上游未修改源码同样存在的 Vite checker `TS5042` |
| `1.37.3` | 通过 | 通过 | 通过；目标 ESLint 同时通过 |

安装器的托管文件清单来自 `frontend/fluidd-overlay/manifest.json`。升级 Fluidd 后即使部分旧文件已不存在，卸载仍会清理其余 V3 标记；空、损坏或根节点不是对象的 `package.json` 不会被误判为官方兼容源码。

## 4. 使用方式

只检查兼容性，不写入：

```bash
./installer/install.sh --check-compatibility \
  --klipper-python ~/klippy-env/bin/python \
  --fluidd-source ~/fluidd-source \
  --fluidd-mode auto
```

旧式配置目录：

```bash
./installer/install.sh \
  --config-dir ~/klipper_config \
  --klipper-python ~/klippy-env/bin/python \
  --device-count 1 \
  --device 'ace1|/dev/serial/by-id/REPLACE_ME'
```

强制只使用独立页面：

```bash
./installer/install.sh --fluidd-mode standalone ...
```

兼容性检查、dry-run 和正常安装都不会重启 Klipper、Moonraker、Fluidd，也不会执行送料、回抽、切刀、烘干或换料动作。

`--check-compatibility` 是只读操作。正常安装先完成 Klipper 和 Fluidd 预检，再进入事务写入；`source` 模式的不兼容错误不会留下部分链接或源码补丁，`auto` 模式则明确报告回退到 `/ace-v3/`。
