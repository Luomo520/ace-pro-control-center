# ACE Pro 管理中心文档索引

## 新任务最短读取路径

1. `../AGENTS.md`：不可违反的安全与协作规则。
2. `PROJECT_MEMORY.zh-CN.md`：产品范围、当前状态和未关闭风险。
3. `DECISIONS.zh-CN.md`：用户已经确认的长期决策和原因。
4. `PRODUCT_BACKLOG.zh-CN.md`：当前优先级、负责人、依赖和关闭条件。
5. `WORK_ORDER_TEMPLATE.zh-CN.md`：本次任务的范围、负责人和验收格式。

完成这四项后，再按任务类型读取专项文档，不需要重新扫描全部历史对话。

## 用户文档

| 文档 | 读者 | 内容 |
| --- | --- | --- |
| `../README.md` | 新用户 | 项目定位、特色、快速安装和入口 |
| `INSTALL.zh-CN.md` | 安装者 | 安装、配置、回滚、卸载和故障处理 |
| `FEATURES.zh-CN.md` | 用户与维护者 | 当前完整功能和限制 |
| `DRIVER-v1.2.0.zh-CN.md` | 调机用户 | 驱动行为、参数和调校边界 |
| `RELEASE-v1.2.0.zh-CN.md` | 安装与升级用户 | v1.2.0 重大变化、升级路径、回滚和已知边界 |
| `ACE_CONFIG_SPECIFICATION.zh-CN.md` | 配置填写者与维护者 | 配置功能总览、五星必填项、分区、依赖和治理规范；不是运行配置 |
| `templates/ace-config-section.template.ini` | 配置维护者 | 新增功能区、必填项、默认项和条件项的注释格式；不可安装 |
| `ACE_CONFIG_DETAILED_STYLE_REFERENCE.zh-CN.md` | 配置维护者 | 历史结构与注释设计依据；不作为当前参数值来源 |
| `AUTO_DRYING_FLOW.zh-CN.md` | 使用者 | 自动跟随打印烘干流程 |

## 开发文档

| 文档 | 用途 |
| --- | --- |
| `DEVELOPMENT.zh-CN.md` | 仓库结构、开发、测试、构建、部署和发布流程 |
| `PROJECT_MEMORY.zh-CN.md` | 当前事实和交接状态 |
| `DECISIONS.zh-CN.md` | 不可无痕改写的产品决策 |
| `PRODUCT_BACKLOG.zh-CN.md` | 从审计结论转换出的产品优先级和执行工作单 |
| `WORK_ORDER_TEMPLATE.zh-CN.md` | 产品经理向子智能体派发任务的标准格式 |
| `../PROTOCOL.md` | ACE 协议、命令和状态接口 |
| `superpowers/specs/` | 已确认功能设计 |
| `superpowers/plans/` | 历史实施计划和测试步骤 |
| `audits/` | 各领域负责人审计报告，不等同于已实现功能 |

## 文档状态规则

- `PROJECT_MEMORY` 只保存当前有效事实、最近验证和未关闭风险。
- `DECISIONS` 保存决策历史，新策略通过新 ADR 替代旧 ADR。
- `FEATURES` 描述当前产品能力，不记录开发过程。
- `CHANGELOG` 只记录版本变化，不代替产品需求或开发说明。
- `audits` 记录某一时间点的检查结论；修复问题后应标注已关闭或重新审计。
- 历史计划不自动代表当前实现，必须用代码和测试核验。

## 配置文档权威顺序

1. 根目录 `ace.cfg` 是唯一可安装模板，也是发布默认值和活动参数的唯一来源。
2. `ACE_CONFIG_SPECIFICATION.zh-CN.md` 规定结构、语义、依赖和变更门槛，不维护
   第二套机器参数或默认值表。
3. `templates/ace-config-section.template.ini` 只供未来编写功能区，不得安装、部署
   或扩写成完整配置。
4. 材料档案必须位于 `[ace]`；历史 `[ace_materials]` 建议已废弃。
5. `ace_config_version`、上下传感器独立消抖和送料/回料绝对硬上限已进入正式
   配置契约；旧配置兼容和失败暂停规则以配置规范及驱动测试为准。
