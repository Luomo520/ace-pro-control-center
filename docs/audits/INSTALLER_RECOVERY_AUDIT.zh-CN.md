# 安装与恢复审计

审计日期：2026-07-28
审计对象：当前未提交工作树中的 `install.sh`、`ui-installer.sh`、`uninstall.sh`、`manifest.sha256`、`tests/installer/`
角色：安装与恢复负责人
验证层级：静态检查 + 清单哈希独立复算；未连接打印机，未执行 Git 写操作，未修改被审计代码

## 1. 工作单

- 目标：确认 `ace.cfg` 去锁迁移、安装范围、兼容提示、失败恢复、最近回滚和首次基线卸载是否满足当前设计。
- 允许修改：仅本审计文档。
- 禁止项：连接打印机、服务重启、物理动作、Git commit/push、覆盖或回退现有改动。
- 验收标准：所有结论有文件与行号；区分已实现、测试覆盖、未验证、风险和建议；提供可执行验收清单。
- 回滚方式：删除本审计文档；被审计文件无改动。

## 2. 结论

总体结论：`ace.cfg` 去锁的主路径已实现，普通安装、仅驱动、仅卡片、完整安装、最近回滚和分范围基线也已有代码与测试骨架；但当前实现还不能认定为“可可靠恢复”。存在两个 P0，发布或部署前应阻断：

1. **P0：归档失败可能破坏原状态且恢复失败被隐藏。** `archive_item` 在 `mv` 成功前先写存在标记，归档过程本身直接移动线上目标；如果 `mv` 或后续归档步骤失败，`restore_item` 会先把仍在原位的目标再次移入隔离目录，再尝试从可能不存在的 `old/` 内容复制。安装路径随后用 `|| true` 丢弃恢复失败；回滚和卸载在“归档当前状态”失败时甚至没有调用恢复。证据：`ui-installer.sh:363-400`、`ui-installer.sh:405-438`、`ui-installer.sh:499-521`、`ui-installer.sh:525-530`、`ui-installer.sh:533-567`。
2. **P0：首次基线不是全局首次安装前快照。** 基线按 `all/driver/card` 分开，并只在对应范围第一次成功时创建。若先装驱动、再完整安装，`first-install-old` 会记录“驱动已安装”的中间状态；完整卸载优先使用该 `all` 基线并忽略更早的驱动基线，因此不能恢复项目首次安装前状态。完整安装后直接执行 `--uninstall-driver` 或 `--uninstall-card` 也会因没有分范围基线而失败。证据：`ui-installer.sh:20-22`、`ui-installer.sh:402-403`、`ui-installer.sh:506-513`、`ui-installer.sh:533-564`、`ui-installer.sh:616-624`。

在上述 P0 关闭、Linux 动态测试通过之前，不建议部署安装器。该结论不否定去锁主路径已经具备，而是说明事务与恢复承诺仍有可复现的结构性缺口。

## 3. 证据

### 3.1 `ace.cfg` 去锁修复

| 分类 | 结论与证据 |
| --- | --- |
| 已实现 | 安装前通过 `cp -L` 解析当前 `printer_data/config/ace.cfg` 的真实内容，再归档软链接本身及项目目录配置：`ui-installer.sh:379-396`。这能覆盖旧链接指向 `~/ace-pro-control-center/ace.cfg` 的典型场景。 |
| 已实现 | preserve 模式优先使用归档的 resolved 内容，并分别复制为项目目录文件和配置目录普通文件；随后断言运行配置不是软链接：`ui-installer.sh:453-470`。 |
| 测试覆盖 | 测试构造旧软链接与唯一内容，检查安装后两个普通副本内容一致、Fluidd/Moonraker 未被仅驱动安装修改，并在卸载驱动后恢复原链接类型与内容：`tests/installer/test-install-scopes.sh:35-73`。 |
| 未验证 | 本轮机器没有 Bash/Git Bash、可用 WSL 发行版、Docker 或 Podman，无法执行 Linux 符号链接动态测试。项目记录称相关测试已通过，但这是历史记录而非本轮独立复验：`docs/PROJECT_MEMORY.zh-CN.md:57-61`。 |
| 风险 | 状态检查把任何软链接都报告为“旧版外部软链接”，没有通过 `readlink` 区分目录内链接、目录外链接、断链或可写链接：`ui-installer.sh:573-587`。 |
| 风险 | 权限命令 `chmod u+rw,go+r` 只增加权限，不移除已有的 group/other 写位或执行位；以 root 运行时还可能生成 root 所有的配置，而 `[ -w ]` 会对运行安装器的账号产生误判：`ui-installer.sh:462-465`、`ui-installer.sh:576-583`。当前测试只检查“可写”，不检查 owner、`go-w` 或精确模式：`tests/installer/test-installer.sh:48-52`、`tests/installer/test-install-scopes.sh:28-32`。 |

### 3.2 安装事务、失败恢复、回滚与卸载

| 分类 | 结论与证据 |
| --- | --- |
| 已实现 | 每次安装使用时间戳与 PID 创建新归档；旧文件按范围移动，存在性由 marker 记录，完成后写 `archive.complete`：`ui-installer.sh:363-400`。 |
| 已实现 | 最近回滚从当前 marker 的 `old_archive` 精确选择上次安装归档，而不是仅按目录名猜测；回滚前也归档当前范围：`ui-installer.sh:525-530`。 |
| 已实现 | 卸载前归档当前状态；没有 `all` 基线时可以组合 driver/card 基线：`ui-installer.sh:533-570`。 |
| 测试覆盖 | 完整安装测试覆盖普通安装、强制更新、最近回滚、完整卸载、归档数量和 Fluidd 权限恢复：`tests/installer/test-installer.sh:79-118`。 |
| 测试覆盖 | 分范围测试覆盖仅驱动、仅卡片、卡片回滚，以及仅存在 driver/card 基线时的组合卸载：`tests/installer/test-install-scopes.sh:55-97`。 |
| 测试覆盖 | 失败测试覆盖“归档已完整、随后因 `ACE_CC_ROOT` 是普通文件而安装失败”的恢复：`tests/installer/test-install-failure.sh:21-43`。 |
| 风险 | 失败测试没有注入 `archive_item` 中途失败、恢复自身失败、信号中断或磁盘写满，不能覆盖 P0 的部分归档状态：`tests/installer/test-install-failure.sh:35-43`。 |
| 风险 | trap 只删除生成配置，不记录当前事务，也不在 `HUP/INT/TERM` 时恢复已经移动的目标：`ui-installer.sh:158-161`。 |
| 风险 | 基线归档没有只读化，也没有逐项目标路径、文件类型、所有者、模式和 SHA-256；manifest 只记录四个根路径与范围：`ui-installer.sh:372-400`。设计要求见 `docs/superpowers/specs/2026-07-28-ace-pro-control-center-installer-design.md:127-141`。 |
| 风险 | 卸载恢复时只依据“基线当时是否存在”决定移走当前同路径对象，没有安装状态清单或内容身份校验；用户后来替换或新建的同名配置会从活动位置移入卸载归档。证据：`ui-installer.sh:405-415`、`ui-installer.sh:549-567`；设计边界见 `docs/superpowers/specs/2026-07-28-ace-pro-control-center-installer-design.md:143-149`。 |

### 3.3 Fluidd/Moonraker 兼容与安装范围

| 分类 | 结论与证据 |
| --- | --- |
| 已实现 | 仅驱动跳过前端兼容判断；完整安装遇到风险可选仅驱动、继续或取消；仅卡片遇到风险走确认；强制模式仍先执行 payload 验证和归档：`ui-installer.sh:338-359`、`ui-installer.sh:488-521`。 |
| 已实现 | 目标目录检查按范围分流：card/all 要求 Fluidd 与 Moonraker，driver/all 要求 Klipper 与 `printer.cfg`：`ui-installer.sh:324-336`。实际写入也按范围分流：`ui-installer.sh:502-505`。 |
| 测试覆盖 | 测试覆盖 Fluidd 低于基线时取消完整安装、高于基线时取消仅卡片、`--yes` 继续仅卡片，以及仅驱动不改 Fluidd/Moonraker：`tests/installer/test-installer.sh:62-79`、`tests/installer/test-install-scopes.sh:38-85`。 |
| 风险 | Moonraker 只检查“版本字符串是否非空”，没有已验证版本范围；例如测试中的 `v0.9.3` 会被当作无风险。证据：`ui-installer.sh:183-194`、`ui-installer.sh:338-343`。 |
| 风险 | Fluidd 风险提示不区分低版本、高版本和未知版本，也没有明确告知高版本会被替换为包内 `v1.37.2`；头部没有显示兼容状态。证据：`ui-installer.sh:228-240`、`ui-installer.sh:338-357`；设计要求见 `docs/superpowers/specs/2026-07-28-ace-pro-control-center-installer-design.md:109-125`。 |
| 风险 | `verify_payload` 不按范围分流。仅驱动也要求 Fluidd、Moonraker 和 Web payload；仅卡片也要求驱动、`ace.cfg`、requirements，并编译驱动：`ui-installer.sh:303-321`、`ui-installer.sh:488-492`。因此不相关文件缺失或损坏会阻断独立范围安装。 |
| 风险 | `--yes` 在发现兼容风险时直接继续原范围，只输出警告，不执行“仅驱动/完整/取消”选择或仅卡片二次确认：`ui-installer.sh:346-357`。自动化语义需要明确，否则 `--yes --install` 可静默选择替换前端。 |

### 3.4 `manifest.sha256`

| 分类 | 结论与证据 |
| --- | --- |
| 已通过测试 | 本轮使用 PowerShell `Get-FileHash -Algorithm SHA256` 独立复算当前清单：358 条、358 个唯一路径、0 缺失、0 格式/重复/哈希错误；`.git/`、`.temporary/`、`.playwright-cli/` 均未列入。关键入口位于 `manifest.sha256:13`、`manifest.sha256:16`、`manifest.sha256:44`、`manifest.sha256:276`、`manifest.sha256:323`、`manifest.sha256:357-358`。 |
| 风险 | 安装器仅在“`sha256sum` 存在且清单文件存在”时校验；缺少命令或缺少清单会跳过哈希验证而继续：`ui-installer.sh:303-313`。这与“强制安装仍执行发布文件校验”的承诺不一致。 |
| 风险 | 清单包含整个仓库的文档、测试和源码，而不是按安装范围实际读取/写入的 payload；当前 358 项中包括 19 个 docs 文件和 28 个 tests 文件。任一无关文档变化都可阻断仅驱动或仅卡片安装。生成规则见 `docs/DEVELOPMENT.zh-CN.md:110-124`。 |
| 未验证 | 清单校验只证明“列出的文件匹配”，不证明应包含的 payload 没有漏列；`verify_payload` 也没有核对清单覆盖集合。 |

### 3.5 包装脚本

- 已实现：`install.sh` 保留用户参数并 `exec sh ui-installer.sh`：`install.sh:1-4`。
- 已实现：`uninstall.sh` 固定转发 `--uninstall`：`uninstall.sh:1-4`。
- 风险：帮助文本没有列出已经支持的 `--uninstall-driver` 和 `--uninstall-card`：`ui-installer.sh:621-626`。

## 4. 已通过测试

### 4.1 本轮独立通过

- `manifest.sha256` 全量复算：通过，358/358 唯一且匹配，0 缺失，0 重复，0 哈希错误。
- 被审计文件只读检查与行号核对：通过。
- 工作树保护检查：通过；除本审计文档与其新目录外，没有修改被审计文件。

### 4.2 仓库记录已通过，但本轮未独立复验

`docs/PROJECT_MEMORY.zh-CN.md:58-60` 记录 Shell 语法、完整安装事务、分范围安装/卸载、最近回滚、失败自动恢复和发布清单校验已通过。三份测试脚本也确实包含对应断言，但本轮环境没有 Bash/Git Bash、Linux WSL、Docker 或 Podman，因此不能把当前工作树的动态 shell 测试标记为本轮已通过。

另外，`tests/installer/test-install-scopes.sh` 和 `tests/installer/test-install-failure.sh` 在 Git 索引中为 `100644`，且测试使用 Bash 专属 `set -o pipefail`；开发文档却以 `sh tests/...` 调用：`tests/installer/test-install-scopes.sh:1-2`、`tests/installer/test-install-failure.sh:1-2`、`docs/DEVELOPMENT.zh-CN.md:84-95`。在 Debian 的 dash 下该调用方式不可靠，应在验收时明确使用 `bash`。

## 5. 缺口

1. 没有部分归档失败、归档恢复失败、安装恢复失败、回滚恢复失败、卸载恢复失败和信号中断测试。
2. 没有 `driver -> all -> uninstall all`、`card -> all -> uninstall all`、`all -> uninstall-driver`、`all -> uninstall-card` 的基线矩阵。
3. 没有测试卸载时用户已替换同名 `ace.cfg` 或 Moonraker/Fluidd 文件的所有权判断。
4. 没有检查 `ace.cfg` 精确权限、owner/group、`go-w`，也没有 root/sudo 安装场景。
5. 没有真正断链、相对外部链接、外部目标不可读、跨文件系统移动失败测试。
6. 没有 Moonraker 支持/不支持/未知版本矩阵；Fluidd 未测试未知版本、继续完整安装和风险下转仅驱动。
7. 没有验证高版本 Fluidd 的提示明确包含“将替换为 v1.37.2”。
8. 没有验证仅驱动/仅卡片在不相关 payload 缺失时仍能独立运行。
9. 没有验证缺少 `manifest.sha256` 或 `sha256sum` 时安装必须失败。
10. 状态命令没有按设计覆盖组件存在性、已安装版本、基线、兼容风险和软链接真实目标；现有测试未覆盖 `--status`。
11. 本轮未进行模拟安装、真机静态验证或真机物理验证；按任务要求也未连接打印机。

## 6. P0/P1/P2 建议

### P0：发布/部署阻断

1. 把归档改成可验证的两阶段事务：先完整复制并校验归档，再原子替换目标；存在 marker 只能在对应旧对象已成功落盘后写入。所有恢复调用必须检查结果，失败时输出原目标、归档和隔离目录的具体路径。
2. 为安装、回滚、卸载和信号退出统一事务恢复；特别修复 `create_archive` 在安装、回滚、卸载三个入口中的失败分支，禁止 `|| true` 吞掉恢复失败。
3. 建立全局“项目首次写入前”基线，同时保存分组件基线；定义混合安装顺序下 `all/driver/card` 卸载语义，并用完整排列测试证明不会恢复到中间安装态。

### P1：合并前完成

1. 归档 manifest 记录每个目标的原路径、类型、链接文本、owner/group、mode、存在性和 SHA-256；首次基线完成后设为只读并验证不可被后续安装覆盖。
2. 增加安装状态清单与文件身份校验，卸载仅移除仍由安装器跟踪的对象；用户后来替换的同名文件保留在活动路径并报告冲突。
3. 将 `ace.cfg` 权限收敛为明确模式并处理 owner；状态检查使用真实链接目标与目标可写性，不把所有链接统一标成旧外部锁定链接。
4. 定义 Moonraker 已验证版本范围，细分 Fluidd 低/高/未知提示；高版本提示明确说明会替换为包内 `v1.37.2`。明确 `--yes` 是否等价于接受前端替换。
5. 按 `all/driver/card` 分开校验和编译 payload；将 `manifest.sha256` 设为必需，缺少校验工具时失败。发布清单与安装 payload 清单分离，避免文档或测试变化阻断独立安装范围。
6. 在 Linux CI 使用 `bash` 运行三份安装器测试，并加入故障注入、权限、真实软链接和混合基线矩阵。

### P2：可维护性与诊断

1. 扩充 `--status`：显示安装范围与版本、每个组件状态、链接真实目标、基线、最近归档、兼容风险和五通传感器三态。
2. 清理或检测遗留 stage 目录，避免 PID 复用或中断后目录影响下次复制：`ui-installer.sh:473-480`。
3. 记录依赖安装副作用；`pip install pyserial` 不在当前文件归档事务中，失败恢复不会回退 Python 环境：`ui-installer.sh:446-470`。
4. 修正帮助文本和测试调用文档，使分范围卸载参数与 Bash 运行方式可发现且一致。

## 7. 可执行验收清单

以下验收必须在 Linux 临时 HOME 或 CI 容器中运行，不连接打印机，不重启服务，不触发物理动作。

### 7.1 基础门槛

- [ ] `sh -n install.sh ui-installer.sh uninstall.sh`
- [ ] `sha256sum -c manifest.sha256`
- [ ] `bash tests/installer/test-installer.sh`
- [ ] `bash tests/installer/test-install-scopes.sh`
- [ ] `bash tests/installer/test-install-failure.sh`
- [ ] 测试前后对仓库执行 `git status --short`，除测试允许的临时目录外无新增改动。

### 7.2 去锁与权限

- [ ] 创建 `printer_data/config/ace.cfg ->` 配置目录外文件的真实 Linux 软链接，记录链接文本、目标 SHA-256、mode 和 owner。
- [ ] 执行仅驱动安装；确认外部目标内容未改，两个安装配置内容与原解析内容一致，运行配置为普通文件。
- [ ] 确认运行配置 owner 是预期打印机用户，mode 不包含 group/other 写位或执行位，Fluidd/Moonraker 服务账号具备预期编辑能力。
- [ ] 执行最近回滚和仅驱动卸载；确认原软链接文本、相对/绝对形式、目标内容、mode 和 owner 完整恢复。
- [ ] 分别验证断链、相对外部链接、不可读目标；安装必须在移动任何目标前失败并给出具体路径。

### 7.3 故障恢复

- [ ] 在归档第 1、2、N 项的 marker 创建、移动、校验阶段分别注入失败；命令非零退出，所有原路径的类型、内容、owner、mode 和哈希与安装前一致。
- [ ] 在驱动复制、配置复制、Fluidd stage、Moonraker 复制、marker 写入阶段分别注入失败；验证自动恢复成功且输出归档/隔离路径。
- [ ] 在恢复复制本身注入失败；确认不会输出“已恢复”，保留现场并报告需要人工处理的三个路径。
- [ ] 在归档和安装每个阶段发送 `TERM`；重新运行状态/恢复命令后不得留下缺失目标或被误用的 stage。
- [ ] 模拟磁盘满、只读目录和跨文件系统 `mv`；验证失败原子性。

### 7.4 基线、回滚与卸载矩阵

- [ ] `all -> rollback -> uninstall all` 恢复项目首次安装前全量哈希与文件类型。
- [ ] `driver -> all -> uninstall all` 恢复项目首次安装前状态，不保留第一次 driver 安装。
- [ ] `card -> all -> uninstall all` 恢复项目首次安装前状态，不保留第一次 card 安装。
- [ ] `driver -> card -> uninstall all` 与 `card -> driver -> uninstall all` 均恢复最早基线。
- [ ] `all -> uninstall-driver` 和 `all -> uninstall-card` 行为与文档一致，且另一范围不变。
- [ ] 安装后由用户替换同名 `ace.cfg`、Moonraker 组件或 Fluidd 文件；卸载不得静默移除用户对象。
- [ ] 每次回滚/卸载前产生新归档，历史归档与首次基线未被覆盖且首次基线只读。

### 7.5 兼容与范围边界

- [ ] Fluidd `低于/等于/高于/未知` x Moonraker `支持/不支持/未知` 全矩阵验证提示和选择。
- [ ] 完整安装风险路径分别验证“仅驱动/继续完整/取消”；取消时目标与归档目录均不变化。
- [ ] 仅卡片风险必须二次确认；高版本提示必须写明将替换为包内 `v1.37.2`。
- [ ] 强制完整安装仍执行 payload 哈希、安装前归档和失败恢复。
- [ ] 删除不相关 card payload 后仅驱动仍可运行；删除不相关 driver payload 后仅卡片仍可运行。
- [ ] 删除 `manifest.sha256` 或隐藏 `sha256sum` 后安装明确失败，不允许降级为未校验安装。

### 7.6 状态与最终判定

- [ ] `--status` 在未安装、旧外部软链接、普通可写文件、普通只读文件、断链和部分安装下输出正确状态。
- [ ] `--status` 显示实际安装版本/范围、每个组件、最近归档、全局/分范围基线及兼容风险，且全程只读。
- [ ] 所有自动测试通过后，仍将真机部署、服务状态和物理动作标记为未验证；只有另行授权并完成打印机变更前后备份后才能进入部署。

## 8. 审计边界

- 已实现：仅代表当前代码存在对应路径，不代表动态行为已在本轮运行。
- 测试覆盖：代表测试脚本有对应断言，不等于当前工作树本轮执行通过。
- 已通过测试：仅限本轮清单独立复算，以及仓库项目记忆明确记录但已单独标注为历史结果的项目。
- 未验证：Shell 动态测试、模拟安装、真机静态状态、服务状态和物理动作。
- 风险：依据当前文件与行号推导的可触发行为；没有修改代码进行修复。
- 建议：供后续修复工作单使用，本次审计不实施。
