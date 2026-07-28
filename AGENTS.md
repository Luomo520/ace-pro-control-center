# Ace Pro Control Center 智能体协作规则

本文件适用于本仓库及全部子目录。开始工作前必须依次阅读：

1. `docs/PROJECT_MEMORY.zh-CN.md`
2. `docs/DECISIONS.zh-CN.md`
3. `docs/DEVELOPMENT.zh-CN.md`
4. `docs/DOCUMENTATION_INDEX.zh-CN.md`
5. `docs/PRODUCT_BACKLOG.zh-CN.md`
6. `docs/FEATURES.zh-CN.md`
7. 与任务对应的设计、安装或驱动文档
8. `docs/WORK_ORDER_TEMPLATE.zh-CN.md`

## 强制边界

- 本项目名称为 **Ace Pro Control Center / ACE Pro 管理中心**；`ACEPROSV08` 仅表示上游来源和兼容身份。
- 当前产品只支持一台 ACE Pro、四个料槽和 DIY Klipper 打印机。
- Fluidd 卡片是主界面，`/ace.html` 是备用控制与诊断页；不得另建网站代替 Fluidd。
- 不得同时加载本驱动、原版 `szkrisz/ACEPROSV08` 和 `Kobra-S1/ACEPRO`。
- 未经用户明确命令，不得 Git commit、push、创建标签或发布 GitHub Release。
- 未经用户明确命令，不得连接打印机部署本地修改。
- 不得删除、覆盖或回退无法确认来源的现有工作区改动。
- 不得输出、记录或提交密码、令牌、私钥及设备凭据。

## 打印机变更

- 只读日志、状态和配置检查不需要备份。
- 修改打印机前，必须执行工作区上级 `AGENTS.md` 规定的变更前备份；失败立即停止。
- 修改后必须完成语法、服务和状态验证，再执行变更后备份。
- 服务重启或任何潜在物理动作前查询 `print_stats`；打印期间不得重启、换料、切刀或回抽。
- 不得把送料、回抽、切刀、加热或工具切换作为自动验证动作。

## 工作方式

- 每项任务先形成工作单：目标、范围、禁止项、文件所有权、验收标准和回滚方式。
- 多智能体并行时必须使用互不重叠的写入范围；产品负责人负责最终集成。
- 任何“已实现”结论必须同时标注证据和验证层级：静态检查、自动测试、模拟安装或真机验证。
- 新决策、已完成的重要功能和剩余风险必须同步更新 `docs/PROJECT_MEMORY.zh-CN.md`。
- 已确认且会影响后续实现的决策必须追加到 `docs/DECISIONS.zh-CN.md`，不得只保留在聊天中。
- 构建、测试、目录或部署流程变化时必须同步更新 `docs/DEVELOPMENT.zh-CN.md`。
- 发布前必须重建并验证 `manifest.sha256`，排除 `.git/`、`.temporary/`、`.playwright-cli/`、`__pycache__/`、`*.pyc` 和 `*.pyo`。
- 最终汇报必须说明：修改内容、验证结果、未验证风险、是否部署打印机、是否提交 GitHub。

## `ace.cfg` 配置治理

- 修改 `ace.cfg`、配置默认值或驱动配置解析前，必须先阅读 `docs/ACE_CONFIG_SPECIFICATION.zh-CN.md`，并使用 `docs/templates/ace-config-section.template.ini` 的注释格式。
- 根目录 `ace.cfg` 是唯一可安装模板；不得另建会与其独立演化的第二套完整运行配置。
- 规范、README、安装文档和 section template 不得复制一整套当前机器值、发布默认值或固定活动参数数量；值和活动键以根 `ace.cfg` 与驱动解析为准。
- 新增活动参数前必须先在 `extras/ace.py` 实现读取、校验和错误提示；驱动未读取的保留需求只能写入规范，不得写成活动参数。
- 新参数必须放入现有功能区或建立有整体说明、依赖和安全边界的新功能区；机械参数使用 `☆☆☆☆☆` 标记并写明单位、测量方法、范围和失败行为。
- 材料档案必须保留在 `[ace]` 内；不得创建没有 Klipper 模块的 `[ace_materials]`。
- 上下传感器独立消抖、送料/回料绝对硬上限和 `ace_config_version` 已进入活动配置；后续修改必须同步驱动、状态契约和回归测试。
- 任何配置契约变化必须同步更新驱动、`ace.cfg`、配置规范、驱动指南、安装教程、项目记忆和测试；参数或派生状态对外暴露时，还必须同步 Moonraker 状态/能力/校验、Fluidd 类型与界面及备用页。
- 变更后必须确认活动键唯一、通用模板不含真实传感器引脚/切刀坐标、默认宏无移动或加热，并重新生成校验清单。
