# Fluidd 前端与 Moonraker 集成审计

审计日期：2026-07-28
审计角色：Fluidd / Moonraker 集成负责人
审计对象：当前未提交工作树中的 `fluidd-source-overlay/`、`fluidd-dist/`、`ace_status_integration/moonraker/`、`ace_status_integration/web/`、相关测试与安装器
审计方式：仅本地只读静态审计与非设备测试；未连接打印机，未修改代码，未执行 Git commit/push

## 1. 结论摘要

**当前版本不能认定为可发布或可安装。** 主体功能已经覆盖 Fluidd 卡片、备用 `/ace.html` 和 Moonraker 白名单 API，但存在以下发布阻断问题：

1. **P0：Fluidd 卡片可在 ACE API 返回 HTTP 404 后绕过 Moonraker 白名单，直接发送 G-code。** 源码在 `fluidd-source-overlay/src/mixins/acePro.ts:240-269`，当前生产块也保留该分支：`fluidd-dist/assets/AceProCard-C6MkFdU-.js:1-3`。这直接违反“所有前端动作经 Moonraker 白名单和参数校验”的项目约束：`docs/PROJECT_MEMORY.zh-CN.md:20-22`。
2. **P0：当前 `manifest.sha256` 无法通过完整校验。** 本轮使用 PowerShell `Get-FileHash -Algorithm SHA256` 独立复算 358 条记录，0 缺失、3 条不匹配：`README.md`、`tests/test_release_docs.py`、`tests/__pycache__/test_release_docs.cpython-312.pyc`。安装器在任何安装范围写入前校验整份清单并在不匹配时退出：`ui-installer.sh:303-313`、`ui-installer.sh:488-500`。清单还纳入多种 `__pycache__`，例如 `manifest.sha256:14-15`、`manifest.sha256:329-342`，与 `.gitignore:4` 冲突，清单会受 Python 版本和测试运行影响。
3. **P0：空白页或安装中断后的恢复保证不成立。** 既有专项审计已确认“部分归档失败可破坏原状态且恢复失败被吞掉”和“首次基线不是全局首次安装前快照”两个 P0：`docs/audits/INSTALLER_RECOVERY_AUDIT.zh-CN.md:18-23`。当前安装成功路径没有对首页、静态资源、Content-Type 或四个 ACE API 做健康检查，复制完成便报告成功：`ui-installer.sh:473-485`、`ui-installer.sh:488-521`。

补充说明：专项安装器审计在其执行时记录清单 358/358 通过：`docs/audits/INSTALLER_RECOVERY_AUDIT.zh-CN.md:65-70`；上述 3 条不匹配是本审计针对**当前工作树**的更新复算结果，不应把两个不同时点的结果混为一谈。

## 2. 审计基准与范围

### 2.1 约束基准

| 基准 | 证据 |
| --- | --- |
| Fluidd 卡片为主入口，`/ace.html` 为备用入口；二者功能一致，仅尺寸和布局可不同 | `docs/PROJECT_MEMORY.zh-CN.md:20`、`docs/DECISIONS.zh-CN.md:19-21` |
| 前端不得执行任意 G-code，所有动作必须经过 Moonraker 白名单和参数校验 | `docs/PROJECT_MEMORY.zh-CN.md:21`、`docs/FEATURES.zh-CN.md:76-85` |
| 物理传感器优先于保存状态，冲突时停止而不是猜测耗材位置 | `docs/PROJECT_MEMORY.zh-CN.md:22`、`docs/FEATURES.zh-CN.md:19-24` |
| Fluidd `v1.37.2` 是完整构建验证基线，其他版本只允许风险提示和可回滚安装 | `docs/PROJECT_MEMORY.zh-CN.md:48,66`、`docs/FEATURES.zh-CN.md:99-111` |
| 参数错误、打印冲突、驱动离线、未处理错误应分别使用 HTTP 400、409、503、500 | `docs/superpowers/specs/2026-07-15-aceprosv08-web-fluidd-design.md:171-172` |
| 材料控件应提供常用项，并接受通过白名单校验的自定义 ASCII 材料标识 | `docs/superpowers/specs/2026-07-15-aceprosv08-web-fluidd-design.md:215` |

### 2.2 本轮限制

- **已执行：** `node --test tests/web/*.test.mjs`，18/18 通过。
- **已执行：** 当前 `manifest.sha256` 的 358 条记录独立复算；结果为 0 缺失、3 条哈希不匹配。
- **已执行：** `fluidd-dist` 静态结构扫描；共 259 个文件、198 个 `assets/` 文件，198 个资源名均出现在 `fluidd-dist/sw.js:1` 的预缓存表中。
- **未验证：** 本机 `python.exe`/`python3.exe` 仅为 Microsoft Store 占位程序，因此未执行 Python 测试。
- **未验证：** 本机没有可用 Bash/Git Bash/WSL 发行版，因此未执行 `tests/installer/*.sh`。
- **未验证：** 本仓库没有完整 Fluidd `package.json`，完整源码位于相邻 `fluidd-develop` 工作区，不能仅凭本仓库重建产物：`docs/DEVELOPMENT.zh-CN.md:99-108`。
- **未验证：** 未连接打印机，未执行 Moonraker/Klipper 运行时、浏览器挂载、移动端/桌面视觉、物理传感器或任何会引发机械动作的测试。

## 3. 功能对照表

判定说明：“一致”只表示当前源码暴露同类功能；没有运行时验证时仍标记为“未验证”。

| 功能 | Fluidd 卡片 | `/ace.html` | Moonraker / 驱动契约 | 判定 |
| --- | --- | --- | --- | --- |
| 连接、设备、温湿度、风扇、当前工具、槽位和位置状态 | 使用 Moonraker REST 状态，并合并 Fluidd 已有对象状态：`fluidd-source-overlay/src/mixins/acePro.ts:198-213`、`fluidd-source-overlay/src/util/acepro.ts:498-569` | REST 加 Klipper WebSocket：`ace_status_integration/web/ace-dashboard.js:370-510` | 每次 GET 查询 `ace`、`save_variables`、三个传感器、`print_stats`、`idle_timeout`：`ace_status_integration/moonraker/ace_status.py:550-576` | **已实现；订阅语义不一致，见 P1** |
| 手动烘干状态、温度、时长、启动和停止 | `fluidd-source-overlay/src/components/widgets/acepro/AceProCard.vue:191-244`、`fluidd-source-overlay/src/mixins/acePro.ts:374-381` | `ace_status_integration/web/ace.html:91-132`、`ace_status_integration/web/ace-dashboard.js:1019-1040` | `ACE_START_DRYING`/`ACE_STOP_DRYING` 严格构造：`ace_status_integration/moonraker/ace_status.py:431-438,488-489` | **已实现；源码功能一致；运行时未验证** |
| 自动跟随打印状态、原因、温度、告警和开关 | 卡片显示状态并对混装/未知材料确认：`fluidd-source-overlay/src/components/widgets/acepro/AceProCard.vue:215-236`、`fluidd-source-overlay/src/mixins/acePro.ts:359-371` | 页面显示状态并执行同类确认：`ace_status_integration/web/ace.html:114-132`、`ace_status_integration/web/ace-dashboard.js:906-923,1230-1249` | 两个无参数白名单命令：`ace_status_integration/moonraker/ace_status.py:490-491` | **已实现；Node 合约测试覆盖；运行时未验证** |
| 槽位材料、颜色和喷嘴参考温度编辑 | 自由输入 combobox、颜色和温度保存：`fluidd-source-overlay/src/components/widgets/acepro/AceProSlotCard.vue:92-145,247-275` | 材料为 select，颜色和温度可编辑：`ace_status_integration/web/ace.html:175-214`、`ace_status_integration/web/ace-dashboard.js:1310-1388` | `ACE_SET_SLOT` 校验索引、材料、RGB、温度：`ace_status_integration/moonraker/ace_status.py:373-400` | **部分一致；自定义材料能力不一致** |
| 材料资料列表和温度 | 有后端资料时替换默认列表：`fluidd-source-overlay/src/components/widgets/acepro/AceProSlotCard.vue:225-253` | 有后端资料时替换本地列表：`ace_status_integration/web/ace-dashboard.js:234-253,538-551` | 状态归一化材料资料：`ace_status_integration/moonraker/ace_status.py:150-178,265-298`；相关测试在 `tests/test_ace_status_component.py:150-186` | **后端资料路径一致；无资料时默认列表不同，运行时未验证** |
| 清空槽位 | 明确按钮和 `EMPTY=1`：`fluidd-source-overlay/src/components/widgets/acepro/AceProSlotCard.vue:155-170`、`fluidd-source-overlay/src/mixins/acePro.ts:315-317` | 未发现清空按钮或发送 `EMPTY=1` 的路径；现有编辑仅提交材料/颜色/温度：`ace_status_integration/web/ace.html:196-214`、`ace_status_integration/web/ace-dashboard.js:1310-1388` | 后端支持 `EMPTY=1`：`ace_status_integration/moonraker/ace_status.py:373-384` | **不一致，违反功能一致性要求** |
| 上方、下方、五通传感器 | 三个状态指示和“诊断传感器”：`fluidd-source-overlay/src/components/widgets/acepro/AceProCard.vue:120-150,330-371,530-545` | 三个状态指示和诊断操作：`ace_status_integration/web/ace.html:62-75,276-292,338`、`ace_status_integration/web/ace-dashboard.js:925-928` | 状态归一化：`ace_status_integration/moonraker/ace_status.py:334-339`；诊断命令在白名单：`ace_status_integration/moonraker/ace_status.py:497` | **显示/诊断一致；不是启用/禁用传感器的配置开关** |
| 冷态预装载、送料/回料探测、完整探测、保存/取消结果、完全卸载、紧急停止 | `fluidd-source-overlay/src/components/widgets/acepro/AceProCard.vue:322-440`、`fluidd-source-overlay/src/mixins/acePro.ts:428-527` | `ace_status_integration/web/ace.html:276-370`、`ace_status_integration/web/ace-dashboard.js:1102-1138` | 确认参数与命令白名单：`ace_status_integration/moonraker/ace_status.py:480-507` | **已实现；源码功能一致；Node 合约测试覆盖** |
| 装载/卸载、换卷、手动送料/回抽、送料辅助、库存、无限续料 | `fluidd-source-overlay/src/mixins/acePro.ts:279-356,389-425` | `ace_status_integration/web/ace-dashboard.js:875-1017,1042-1100` | 固定白名单和打印中写命令阻断：`ace_status_integration/moonraker/ace_status.py:480-533` | **已实现；运行时未验证** |
| 错误提示 | 命令错误保存为持久警告：`fluidd-source-overlay/src/mixins/acePro.ts:254-258`、`fluidd-source-overlay/src/components/widgets/acepro/AceProCard.vue:553-570` | API、WebSocket 和命令错误使用临时 toast：`ace_status_integration/web/ace-dashboard.js:378-401,450-510,819-870,1502-1511` | 返回结构化错误体：`ace_status_integration/moonraker/ace_status.py:613-631` | **有提示但语义不同；HTTP 状态码和轮询错误有缺口** |
| 命令入口 | 正常路径 POST `/server/ace/command`，404 后回退直接 G-code：`fluidd-source-overlay/src/api/acePro.ts:34-42`、`fluidd-source-overlay/src/mixins/acePro.ts:240-269` | 始终 POST `/server/ace/command`，不直接执行 G-code：`ace_status_integration/web/ace-dashboard.js:819-870` | 仅接受 `COMMAND_BUILDERS` 中命令：`ace_status_integration/moonraker/ace_status.py:480-533` | **安全行为不一致；Fluidd 为 P0** |

## 4. 状态订阅与一致性

### 4.1 已实现

- Fluidd 卡片在创建时立即查询，并每 5 秒调用 `/server/ace/status`：`fluidd-source-overlay/src/mixins/acePro.ts:31-44,198-214`。
- `/ace.html` 建立 Moonraker WebSocket、断线后定时重连，并订阅 Klipper `ace` 对象：`ace_status_integration/web/ace-dashboard.js:370-447`。
- Moonraker GET 状态查询合并驱动、保存变量、传感器与打印状态；后续查询失败时可返回带 `stale=true` 的最近缓存：`ace_status_integration/moonraker/ace_status.py:550-593`。

### 4.2 风险与缺口

1. **Fluidd 没有 ACE 专用 WebSocket 订阅。** 卡片只做 5 秒 REST 轮询，命令完成后再主动刷新：`fluidd-source-overlay/src/mixins/acePro.ts:31-44,198-214,240-253`。状态最多延迟一个周期，且并发慢请求可能乱序覆盖；没有请求序号、取消或时间戳保护。
2. **备用页只订阅 `ace`。** `printer.objects.subscribe` 未订阅 `save_variables`、上/下传感器或归一化 Moonraker ACE 状态：`ace_status_integration/web/ace-dashboard.js:405-417`。它依赖额外 REST 补齐数据，因此 WebSocket 本身不能保证全部界面字段实时一致。
3. **备用页断开 WebSocket 时也停止 REST 轮询。** 定时器只有在 `wsConnected` 为真时才调用 `loadStatus()`：`ace_status_integration/web/ace-dashboard.js:277-288`。断线阶段既没有实时推送，也没有 REST 降级刷新。
4. **物理传感器没有参与当前工具权威判定。** Moonraker 从 `save_variables.ace_current_index` 得出 `current_tool`，并据此标记槽位 `loaded/active`：`ace_status_integration/moonraker/ace_status.py:259-281`；传感器只作为独立字段返回：`ace_status_integration/moonraker/ace_status.py:334-339`。保存状态与物理传感器冲突时，API 仍可能显示过期的“已装载”槽位，不符合物理传感器优先约束。
5. **首次状态读取失败被包装为普通离线状态。** 只有已有 `_last_status` 时才设置 `stale=true` 和警告；首次失败返回默认离线状态：`ace_status_integration/moonraker/ace_status.py:581-593`，客户端无法区分“确认离线”和“查询失败”。

## 5. 命令白名单、错误与安全边界

### 5.1 已实现

- Moonraker 注册四个固定端点：`/server/ace/status`、`slots`、`capabilities`、`command`：`ace_status_integration/moonraker/ace_status.py:536-547`。
- 22 个命令使用独立构造器，未知命令、未知/缺失参数、索引、移动范围、RGB、材料字符、温度和确认参数均在服务端校验：`ace_status_integration/moonraker/ace_status.py:373-533`。
- 打印中对库存修改、普通换料、移动、启动烘干、启用类功能和标定动作做服务端阻断：`ace_status_integration/moonraker/ace_status.py:525-533`。
- 单元测试源码覆盖确认参数、状态归一化、材料资料、RGB/材料拒绝、未知命令、打印保护和处理器调用：`tests/test_ace_status_component.py:39-108,110-317,347-480`。

### 5.2 风险

1. **P0 白名单旁路。** Fluidd 的 404 回退对每个动作拼接并发送原始 G-code：`fluidd-source-overlay/src/mixins/acePro.ts:240-269`。这不仅绕过参数白名单，也绕过 Moonraker `printing` 保护；生产块中同样存在：`fluidd-dist/assets/AceProCard-C6MkFdU-.js:1-3`。
2. **声明的 HTTP 状态码没有发出。** `AceRequestError` 保存 `status_code`：`ace_status_integration/moonraker/ace_status.py:24-36`，但处理器捕获后只返回 `{success:false}`：`ace_status_integration/moonraker/ace_status.py:613-631`。因此 400/409/503 很可能仍以 HTTP 200 返回，和设计契约不符，也会使依赖 HTTP 状态的客户端分支失效。
3. **Fluidd 状态轮询错误被静默吞掉。** 除 404 外，`pollAceProApi()` 不设置错误、不清空旧状态也不标记 stale：`fluidd-source-overlay/src/mixins/acePro.ts:198-213`。用户可能在没有告警时继续看到旧数据。
4. **错误呈现不一致。** Fluidd 保留命令错误直到下次成功，备用页 toast 数秒后消失：`fluidd-source-overlay/src/mixins/acePro.ts:249-268`、`ace_status_integration/web/ace-dashboard.js:1502-1511`。功能可用，但不满足严格的同等诊断体验。

## 6. Fluidd 基线、构建产物与安装兼容

### 6.1 已实现

- 包内基线明确为 Fluidd `v1.37.2`：`fluidd-dist/release_info.json:1`、`ui-installer.sh:6`。
- 安装器可识别非基线 Fluidd 或无法识别的 Moonraker，交互模式允许取消：`ui-installer.sh:338-358`。
- Fluidd 目录、Moonraker 组件、备用页和配置会在安装前归档，恢复路径存在；旧 `config.json` 会复制到新 Fluidd stage：`ui-installer.sh:363-438,473-485`。
- 当前 `fluidd-dist/index.html` 引用存在的主 JS/CSS：`fluidd-dist/index.html:22-39`；目录中只有一组当前 `AceProCard-*.js`、`AceProCard-*.css` 和 `AcePro-*.js`，且所有 198 个 assets 文件名均进入 `fluidd-dist/sw.js:1` 预缓存表。

### 6.2 测试覆盖

- 安装器测试源码覆盖低版本取消、高版本取消、`--yes` 继续、分范围安装和回滚：`tests/installer/test-installer.sh:62-105`、`tests/installer/test-install-scopes.sh:35-99`。
- 本轮未能执行 Shell 测试，因此上述为**测试代码存在**，不是本轮通过结果。
- Node 测试覆盖卡片布局、自动烘干、标定命令、显式确认和材料资料字段：`tests/web/fluidd-card-layout.test.mjs:6-167`、`tests/web/auto-drying-page.test.mjs:6-43`、`tests/web/calibration-page.test.mjs:6-84`、`tests/web/material-profiles-card.test.mjs:6-41`。

### 6.3 未验证与风险

1. **当前 payload 完整性校验失败。** 3 条哈希不匹配会让有 `sha256sum` 的目标机在任何范围安装前退出：`ui-installer.sh:303-313,488-500`。
2. **清单不是稳定的安装 payload 清单。** 它包含测试、文档和多版本 Python 缓存；这些不参与目标运行，却能阻断仅驱动或仅卡片安装。安装器也没有按 `all/driver/card` 范围选择校验项目：`ui-installer.sh:303-321`。
3. **缺少清单或 `sha256sum` 时会跳过校验。** `verify_payload()` 仅在二者同时存在时校验：`ui-installer.sh:303-313`，与发布完整性保证冲突。
4. **其他 Fluidd 版本没有构建级兼容保证。** `--yes` 在发现风险时直接继续原范围：`ui-installer.sh:338-358`，高版本也会被整套替换为包内 v1.37.2，而提示没有明确表达降级/替换后果。
5. **Moonraker 只检查能否读到版本字符串，没有支持版本范围。** `ui-installer.sh:183-194,338-343`。
6. **无安装后健康检查。** 安装器替换整个 Fluidd 树，只保留旧 `config.json`，但没有验证 HTTP 200、HTML Content-Type、主资源可取、ACE 四端点可用或页面非空：`ui-installer.sh:473-485,488-521`。
7. **空白页恢复仍受两个恢复 P0 影响。** 详见 `docs/audits/INSTALLER_RECOVERY_AUDIT.zh-CN.md:18-23`；在这些问题关闭前，不能把“存在 archive/restore 函数”等同于“失败后可靠回滚”。
8. **产物仅通过结构检查。** 本仓库不能独立生产构建，未证明当前 overlay、相邻完整源码和 `fluidd-dist` 完全同源；开发手册也明确要求在完整 Fluidd 工作区构建：`docs/DEVELOPMENT.zh-CN.md:99-108`。

## 7. 测试覆盖与缺口

### 7.1 本轮通过

| 测试 | 结果 | 能证明的范围 |
| --- | --- | --- |
| `node --test tests/web/*.test.mjs` | 18/18 通过 | 关键标签、源码片段、命令名、确认字段、布局 CSS 和材料资料字段存在 |
| PowerShell SHA-256 独立复算 | 358 条，0 缺失，3 不匹配 | 当前发布清单不能通过安装器的完整校验 |
| `fluidd-dist` 静态资源扫描 | 259 文件、198 assets、0 个 assets 未进入 SW 预缓存 | 当前目录结构没有明显遗漏的静态资源；不证明浏览器可运行 |

### 7.2 测试性质与缺口

现有四个 Web 测试主要通过 `readFile()` 和正则匹配源码，例如 `tests/web/material-profiles-card.test.mjs:6-41`、`tests/web/fluidd-card-layout.test.mjs:110-167`。它们没有挂载 Vue 组件，也没有模拟 Axios/fetch/WebSocket、Moonraker 鉴权、并发轮询或浏览器缓存。

缺少以下动态测试：

1. API 404 时必须 fail closed，且绝不调用 Fluidd `sendGcode()`。
2. REST/WebSocket 断开、重连、超时、乱序响应和缓存 stale 状态。
3. Fluidd 卡片与 `/ace.html` 的逐功能操作矩阵，包括清空槽位和自定义材料。
4. Moonraker 400/409/503/500 的真实 HTTP 状态、错误体、鉴权和客户端显示。
5. 保存状态与物理传感器冲突时的停止、告警和 UI 呈现。
6. 编辑材料/颜色/温度期间轮询刷新不覆盖未提交输入。
7. v1.37.2 的完整测试、类型检查、lint、生产构建及 overlay-to-dist 可追溯性。
8. 移动端与桌面真实浏览器布局、缓存更新、Service Worker 更新和空白页检测。
9. Fluidd 低于/等于/高于/未知版本与 Moonraker 支持/不支持/未知版本的安装矩阵。
10. 归档中途失败、恢复失败、磁盘满、信号中断、健康检查失败后的自动回滚。

## 8. 优先级建议

### P0：发布与部署阻断

1. 删除 Fluidd `executeAceCommand()` 的原始 G-code 回退；ACE API 不存在或失败时必须显示不可用并停止操作。增加单元测试断言 404、网络错误和 5xx 均不会调用 `sendGcode()`。
2. 重新定义并生成稳定的安装 payload 清单，排除 `__pycache__`、测试运行产物及非安装范围文件；按 `all/driver/card` 校验。发布前要求 `sha256sum -c manifest.sha256` 100% 通过，缺少清单或校验工具时失败。
3. 关闭 `docs/audits/INSTALLER_RECOVERY_AUDIT.zh-CN.md:18-23` 的两个恢复 P0；恢复失败必须向上传播并保留现场，首次基线必须真正代表项目首次安装前状态。
4. 在报告安装成功前验证 Fluidd 首页、Content-Type、主 JS/CSS、ACE 页面和四个 Moonraker API；任何失败自动恢复并再次验证旧版本可用，防止空白页留在线上。

### P1：合并前完成

1. 为 `/ace.html` 增加清空槽位；把材料控件改为与 Fluidd 等价的常用项加受校验自定义 ASCII 输入，并统一无后端资料时的默认列表。
2. 让归一化状态以实时传感器和可信驱动位置为权威；保存索引冲突时返回明确 warning/uncertain，禁止显示确定的 loaded 状态。
3. 让 Moonraker 处理器真正发出 400/409/503/500，同时保持结构化错误体；客户端测试真实 HTTP 行为。
4. 统一状态策略：备用页在 WebSocket 断开时继续 REST 降级轮询；Fluidd 增加响应序号/取消或使用统一订阅，防止旧响应覆盖新状态。
5. Fluidd 对轮询失败显示 stale/错误，备用页保留关键错误直到确认或恢复；统一两端诊断语义。
6. 定义 Moonraker 支持版本范围；对 Fluidd 高版本明确提示将替换为 v1.37.2，明确 `--yes` 的风险接受语义。

### P2：可维护性与可追溯性

1. 将前端功能对照表转为共享数据驱动测试，逐项验证两端控件、参数、确认、禁用条件和错误提示。
2. 保存 v1.37.2 构建命令、依赖锁、源码提交、overlay 哈希和 dist 哈希，建立 overlay-to-dist 可追溯记录。
3. 增加 Playwright 桌面/移动端、Service Worker 更新和资源 404 回归；安装器健康检查复用同一套最小检查清单。

## 9. 验收清单

### 前端与 Moonraker

- [ ] Fluidd 和 `/ace.html` 的所有写操作只调用 `/server/ace/command`；代码和构建产物均不存在 ACE 原始 G-code 回退。
- [ ] 两端逐项具备状态、手动/自动烘干、槽位编辑、清空、材料资料、自定义材料、三传感器状态/诊断、预装载、完整标定、送料/回抽、换料、库存和无限续料。
- [ ] 两端对相同命令使用相同参数、确认要求、打印中禁用规则和错误语义。
- [ ] Moonraker 未知命令/参数返回 400，打印冲突返回 409，驱动离线返回 503，未处理错误返回 500，并保留结构化错误体。
- [ ] WebSocket 断开时备用页继续 REST 刷新；重连后无重复订阅、重复通知或状态回退。
- [ ] Fluidd 并发轮询不会让旧响应覆盖新状态；失败时明确显示 stale/错误。
- [ ] 保存索引与物理传感器冲突时显示 uncertain/warning，不把槽位显示为确定 loaded，也不允许危险动作继续。
- [ ] 编辑中的材料、颜色和温度不会被轮询覆盖，保存后两端刷新一致。

### 测试与构建

- [ ] Python Moonraker/驱动测试全部通过，包含真实 HTTP 状态与冲突状态测试。
- [ ] Node 前端单元测试全部通过，并加入挂载后的 Vue、fetch/Axios 和 WebSocket 行为测试。
- [ ] 在完整 Fluidd v1.37.2 工作区完成单元测试、类型检查、lint 和生产构建。
- [ ] Playwright 在桌面与移动视口完成两端逐功能操作矩阵，无重叠、空白页、资源 404 或控制台异常。
- [ ] 新构建只有一组当前 ACE 哈希资源，`index.html`、动态 import 和 `sw.js` 全部引用存在文件。
- [ ] 记录完整源码基线、overlay、依赖锁和 dist 哈希，能够从记录重现相同产物。

### 安装、兼容与回滚

- [ ] 当前安装 payload 清单无缓存/测试产物，按安装范围复算 100% 通过；缺少清单或校验工具时明确失败。
- [ ] Fluidd `低于/等于/高于/未知` x Moonraker `支持/不支持/未知` 全矩阵验证提示、选择和 `--yes` 行为。
- [ ] 安装后首页返回 HTML Content-Type，主 JS/CSS 和 ACE 页面可取，四个 API 返回预期状态。
- [ ] 在归档、复制、替换、权限、marker、健康检查各阶段注入失败，均恢复旧页面和旧 API；恢复失败不得报告成功。
- [ ] `all -> rollback -> uninstall all` 恢复项目首次安装前的文件内容、类型、链接、所有者和权限。
- [ ] 在实际设备验收前先确认 `print_stats` 非 printing；本审计没有连接打印机，也没有执行任何设备动作。

## 10. 最终判定

| 分类 | 判定 |
| --- | --- |
| 已实现 | 四端点、严格命令构造器、打印保护、主体状态与控制、手动/自动烘干、材料资料、三传感器显示/诊断、标定与高级动作均有实现 |
| 测试覆盖 | Web 源码合约测试 18/18 本轮通过；Moonraker、驱动和安装器存在较广测试源码，但本轮未能执行 Python/Shell 套件 |
| 未验证 | 真实 Moonraker HTTP、Klipper/打印机状态、浏览器交互、移动/桌面视觉、完整 Fluidd v1.37.2 重建、非基线兼容和故障回滚 |
| 风险 | 3 个发布阻断面：Fluidd 白名单旁路、当前 manifest 失败、安装恢复/首次基线 P0；另有功能一致性、物理状态权威、HTTP 状态和订阅降级缺口 |
| 建议 | 完成全部 P0 后再进入集成验收；P1 关闭并通过验收清单后，才可声称 Fluidd 卡片与 `/ace.html` 功能一致且安装可回滚 |
