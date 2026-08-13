# Attendance 考勤 Provider

本仓库只拥有考勤业务真相，是 UXAssistant Gateway 后面的 `ATTENDANCE` Provider。Telegram Bot 凭据、更新获取、命令菜单、callback answer、文件下载和消息发送全部由 Gateway 负责；Attendance 不直接调用 Telegram Bot API。

## 主要能力

- 员工注册、审批状态和身份绑定。
- 群签到、签退、离岗、返岗及相关业务校验。
- 截图识别与考勤记录持久化。
- 个人统计、群汇总、CSV 导出和班表 WebApp。
- Google Sheets 班表、测试群和业务群同步。
- 持久化 Provider 动作、lease/retry、前驱依赖和 terminal receipt 收敛。

已退役的旧 Telegram handler、Bot client、polling/webhook、leave application、temporary leave approval、QC 和 legacy notification 不属于当前产品，不得通过配置或 dormant entrypoint 恢复。

## Gateway 合同

- `POST /integration/gateway/v1/events`：接收并幂等处理 Gateway Event。
- `POST /integration/gateway/v1/delivery-receipts`：接收动作终态回执。
- `POST /internal/v1/actions`：由 Attendance worker 向 Gateway 提交持久异步动作。
- `GET /internal/v1/telegram-files/{fileRef}`：读取 Gateway 授权的 Telegram 文件内容。
- `/api/v1/webapp/session`：用 Gateway 签发的一次性交换凭据换取 Attendance 自有 WebApp session。

Gateway 与 Attendance 使用方向不同的 service credential。Gateway `202 ACCEPTED` 不是发送成功；只有 `DELIVERED` 终态回执才能把对应业务动作标记为 delivered。

群摘要等异步群动作只接受 Gateway 动态 group-route directory 返回的 Attendance routes。唯一人工群配置位于统一 public manifest 的 `components.attendance.groups`；Gateway 按 title 发现并分类 0..N 个群，Attendance 将观察到的 chat ID/route 写入动态 registry。维护者不填写 chat ID 或 routeKey，也不得从 `chatId` 计算路由或回退旧目标。0 个 Attendance 群时 Provider、scheduler 和 worker 仍可 readiness，群摘要 fan-out 为空。

公开配置、roster/capability 清单、root-only binding 和 restart 规则见 [Attendance 统一配置维护指南](docs/attendance-public-config.md)。

## 测试主线与环境

本仓库唯一的长期测试分支是 `main`，`/srv/ux` 隔离测试环境只从 `main` 构建。当前测试机器人显示名为“UX助手”，username 为 `@yyux_helper_bot`；Bot Token 与 Telegram 连接只属于 UXAssistant-Gateway，本仓库只通过 Gateway 使用该机器人。

未来计划的独立 `production` 分支尚未创建。生产机器人、群、凭据、分支和部署需要新的明确授权。

## 目录

- `gateway_provider/`：严格合同、事件入口、业务动作映射和 Provider 组装。
- `domain/`、`services/`：考勤业务规则与用例。
- `repositories/`：Attendance 自有 PostgreSQL 真相。
- `tasks/provider_worker.py`：持久 Gateway 动作投递 worker。
- `tasks/provider_scheduler.py`：日报、群汇总和后台调度。
- `web/`、`shift_web_app.py`：班表 WebApp 与 Gateway session 交换。
- `migrations/`：Attendance 数据库迁移。
- `test_*.py`：产品合同、业务、持久化和 clean-break 回归。

## 本地环境

建议使用独立虚拟环境：

```bash
python -m venv .venv
source .venv/bin/activate
python -m pip install -r requirements.txt -r requirements-dev.txt
```

`.env.example` 只用于本地单元测试；共享 `uxassistant-test` 不读取 checkout `.env`。共享测试的公开值来自统一 manifest，私密值来自 root-only file binding。不得提交数据库密码、Gateway token、AI key、Google Service Account、Sheet 对象标识、可复用 Telegram session/auth key 或其他凭据。Telegram numeric ID 是公开诊断信息，但动态群 ID/route 不作为人工运行配置提交。

## 检查

```bash
python -m compileall domain gateway_provider infra repositories services tasks web
python -m pytest -q
```

需要 PostgreSQL 的测试必须指向独立测试数据库，并串行运行会重建共享表的用例。不得把测试连接指向生产数据库。

常用进程入口：

```bash
python -m gateway_provider.entrypoint
python -m tasks.provider_worker
python -m tasks.provider_scheduler
python shift_web_app.py
```

启动时如果发现 Bot Token、Telegram SDK、直连 Bot API、协议摘要漂移或必需数据库能力缺失，应立即失败，不提供旧 Bot fallback。

## WebApp 调试

WebApp 身份只来自 Gateway session。排查 401 时应重新调用既有 Gateway session exchange，不在 Attendance 内验证 Telegram `initData`，也不引入 Bot Token。

## 生产约束

- 本仓库不是 Telegram owner，不得主动私聊、群发、上传附件或拥有 webhook/polling。
- 不得跨库读取 Gateway 或 OmniAI2 数据。
- 不得恢复已删除的旧路由和兼容 handler。
- 数据库迁移、部署、停服和生产切换必须单独授权；运行测试不会自动执行生产操作。
