# ACE Pro 管理中心开发手册

本手册用于让新的开发者或智能体在不依赖聊天历史的情况下继续工作。产品范围和当前状态见 `PROJECT_MEMORY.zh-CN.md`，已确认决策见 `DECISIONS.zh-CN.md`。

## 1. 仓库布局

| 路径 | 作用 | 是否直接编辑 |
| --- | --- | --- |
| `extras/ace.py` | Klipper ACE 主机驱动 | 是 |
| `ace.cfg` | 发布配置模板 | 是 |
| `ace_status_integration/moonraker/ace_status.py` | Moonraker 组件 | 是 |
| `ace_status_integration/web/` | 备用 `/ace.html` | 是 |
| `fluidd-source-overlay/` | 经过审核的 Fluidd 源码增量 | 是 |
| `../fluidd-develop/` | Fluidd `v1.37.2` 完整构建工作区 | 同步 overlay 后构建 |
| `fluidd-dist/` | 安装器部署的完整生产构建 | 只由验证后的构建替换 |
| `tests/` | Python、Node 和安装器测试 | 是 |
| `ui-installer.sh` | 一体化安装、回滚和卸载 | 是 |
| `.temporary/` | 本地构建和部署暂存 | 不发布、不纳入清单 |
| `.playwright-cli/` | 浏览器测试状态 | 不发布、不纳入清单 |

不要直接在 `fluidd-dist` 中手改业务逻辑。先修改 overlay 和对应的 `../fluidd-develop/src`，通过测试与构建后整体替换产物。

## 2. 开发前检查

```powershell
Set-Location 'C:\path\to\ace-pro-control-center-source'
git status --short
node -v
pnpm.cmd -v
git --version
```

Python 测试可以使用系统 Python 3.11/3.12 或 Codex 工作区运行时。前端当前工具链为 pnpm `11.10.0`，Fluidd 构建基线为 `v1.37.2`。

开始前必须创建工作单，记录允许修改的文件和验收标准。工作区可能已有大量未提交修改，不得清理或回退。

## 3. 跨层变更顺序

涉及新功能时按以下顺序设计和实现：

1. 在驱动中定义状态、配置、G-code 命令和安全边界。
2. 为驱动添加单元测试，覆盖成功、失败、打印中、断联和传感器冲突。
3. 在 Moonraker 中归一化状态，并为命令添加固定白名单与严格参数校验。
4. 同步 Fluidd 卡片和备用页，不在两个前端重复计算驱动策略。
5. 更新配置说明、功能清单、决策记录和安装教程。
6. 运行全套测试和构建，再生成发布清单。

任何一层新增能力都必须在 `capabilities` 或等效状态中可发现，前端应对旧后端缺少能力时安全降级。

## 4. 本地测试

### Python 驱动与 Moonraker

```powershell
python -m unittest discover -s tests -p "test_*.py" -v
```

覆盖范围包括驱动送料/回抽、自动烘干、自动探测、材料资料、配置布局、Moonraker 命令构造和发布文档。

### 备用页面

```powershell
node --test tests/web/*.test.mjs
```

覆盖卡片布局契约、备用页烘干、材料资料和自动探测界面逻辑。

### Fluidd 源码

```powershell
Set-Location 'C:\path\to\fluidd-develop'
pnpm.cmd test:unit --run
pnpm.cmd type-check
pnpm.cmd lint
pnpm.cmd build
```

如果只修改 ACE 工具函数，可先运行：

```powershell
pnpm.cmd test:unit -- src/util/acepro.test.ts --run
```

### 安装器

在 Git Bash 中从仓库根目录运行：

```bash
sh -n ui-installer.sh
sh -n install.sh
sh -n uninstall.sh
bash tests/installer/test-installer.sh
bash tests/installer/test-install-scopes.sh
bash tests/installer/test-install-failure.sh
bash tests/installer/test-transaction-faults.sh
bash tests/installer/test-mixed-baselines.sh
```

Windows Git Bash 可能把 `ln -s` 模拟为普通文件。软链接类型恢复必须保留 Linux 环境严格断言，Windows 只作为额外兼容测试。

推送到 `main` 后，`.github/workflows/release-validation.yml` 会在 Ubuntu 上重复执行 Python、Web、Shell、五组安装器和清单测试。正式标签和 Release 只能在该工作流通过后创建；Ubuntu 测试用于验证真实 POSIX 软链接类型和目标恢复。

## 5. Fluidd 构建产物

1. 将 `fluidd-source-overlay` 中每个文件同步到 `../fluidd-develop` 对应路径。
2. 在完整 Fluidd 工作区执行单元测试、类型检查、lint 和生产构建。
3. 将当前 `fluidd-dist` 移入 `.temporary/` 的时间戳目录，不删除历史暂存。
4. 把 `../fluidd-develop/dist` 完整复制为新的 `fluidd-dist`。
5. 检查 `index.html` 和 `sw.js` 引用的资源全部存在。
6. 确认只存在当前构建的一组 `AceProCard-*.js` 与 `AceProCard-*.css`，不得混入旧哈希资源。

本仓库不包含 Fluidd 完整 `package.json`，所以不能只在 overlay 目录运行构建。

## 6. 发布清单

所有代码、文档、测试和构建产物稳定后，在 Git Bash 运行：

```bash
find . -type f \
  ! -path './.git/*' \
  ! -path './.temporary/*' \
  ! -path './.playwright-cli/*' \
  ! -path './release-assets-v*/*' \
  ! -path '*/__pycache__/*' \
  ! -name '*.pyc' \
  ! -name '*.pyo' \
  ! -name 'manifest.sha256' \
  -print0 | sort -z | xargs -0 sha256sum > manifest.sha256
sha256sum -c manifest.sha256
```

修改清单后必须重新运行安装器测试，因为安装器会在任何写入前验证该清单。

## 7. 模拟安装验收

安装器测试至少验证：

- 完整安装、仅驱动和仅卡片互不越界。
- 旧配置内容在更新时被保留。
- `printer_data/config/ace.cfg` 是普通可写文件，不是目录外软链接。
- Fluidd 非基线版本可取消或只装驱动。
- 最近回滚恢复上一次状态。
- 卸载恢复首次安装前基线。
- 任意 driver/card/all 安装顺序的完整卸载恢复项目第一次写入前状态。
- 归档、替换、恢复和信号中断故障不会丢失原目标。
- 任一步骤失败后恢复原 Fluidd、Moonraker、Klipper 和配置状态。
- `.temporary`、`.playwright-cli` 和凭据不进入发布清单。

## 8. 真机部署门槛

真机部署是独立阶段，不能因为本地测试通过而自动执行。

1. 用户明确要求部署。
2. 只读查询 `print_stats`，确认没有打印任务。
3. 按上级 `AGENTS.md` 执行变更前备份；失败立即停止。
4. 上传到临时路径并验证文件完整性，再原子替换目标。
5. 只做 Python/配置语法和服务状态验证；不得自动执行物理动作。
6. 用户现场确认后再手动测试送料、回抽、切刀或换料。
7. 完成变更后备份，并汇报两个备份目录和验证结果。

## 9. GitHub 发布门槛

只有用户明确要求时才执行 commit、push、标签或 Release。发布前必须确认：

- `VERSION`、`CHANGELOG.md`、README 和专项版本文档一致。
- GPL-3.0 来源和第三方许可说明完整。
- Python、Node、Fluidd、安装器和清单验证全部通过。
- 截图来自当前构建且不包含隐私信息。
- 工作区差异只包含计划发布内容。
- 远端分支、标签、Release 附件和 SHA-256 相互一致。

## 10. 文档更新触发器

| 变化 | 必须更新 |
| --- | --- |
| 产品范围或用户确认的策略 | `DECISIONS.zh-CN.md`、`PROJECT_MEMORY.zh-CN.md` |
| 新功能或删除功能 | `FEATURES.zh-CN.md`、README、CHANGELOG |
| 配置项或默认值 | `ace.cfg`、驱动说明、安装教程 |
| API、命令或状态字段 | `PROTOCOL.md`、功能清单、前端类型与测试 |
| 构建、测试或部署流程 | `DEVELOPMENT.zh-CN.md` |
| 安装、回滚或卸载行为 | `INSTALL.zh-CN.md`、安装器设计和测试 |
| 当前验证/部署/发布状态 | `PROJECT_MEMORY.zh-CN.md` |
