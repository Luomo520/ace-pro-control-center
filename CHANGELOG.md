# 更新日志

## v0.2.0 - 2026-07-15

- 修复安装或恢复 Fluidd 后由于目录权限过严，Nginx 无法读取 JavaScript，页面显示空白的问题。
- 安装完成和卸载恢复都会自动设置 Fluidd 文件为 Web 服务可读权限。
- 修复 ACEPROSV08 烘干状态读取，并兼容 `dryer`、`dryer_status`、`state` 和 `target_temperature` 字段别名。
- 烘干剩余秒数自动转换为分钟，手动修改的烘干温度不会被状态轮询覆盖。
- 增加 `ABSCF`、`PAHTCF`、`PETCF` 和 `PEEK` 耗材类型，并按材料设置默认烘干温度。
- 更新发布校验范围，避免用户修改未被安装器写入的驱动配置后无法更新面板。

## v0.1.0 - 2026-07-15

- 首次发布 ACEPROSV08 专用 Fluidd 卡片与中文独立页面迁移版。
- 新增 Moonraker `ace_status` 适配层，提供状态、料槽、能力和命令四个 API。
- 命令执行改为严格白名单，`ACE_SET_SLOT` 使用 ACEPROSV08 的 `INDEX` 参数。
- 新增字符菜单安装器，支持安装/更新、强制安装、卸载恢复和状态检查。
- 安装和卸载前均创建备份，备份目录为 `~/.local/share/aceprosv08-ui/backups/`。
- Fluidd 卡片和独立页面迁移自旧 ACE Pro UI，并补齐中文说明和第三方来源声明。
- 修复 Moonraker POST 请求读取方式，命令端点使用 `WebRequest.get_args()`。
- 修复 API 失败被 Fluidd 误判为成功，以及颜色/材料保存后恢复旧值的问题。
- 增加上下传感器状态、手动送料/回抽、助推、换卷、无限续料和诊断控制。
- RGB 参数改为严格校验，不再静默钳制越界值。
- 安装器记录文件安装前是否存在，卸载和失败回滚可恢复完整初始状态。
- 从 Fluidd v1.37.2 完整源码重新构建，并通过前端、Python 和隔离安装器测试。
