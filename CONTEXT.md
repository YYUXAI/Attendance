# Attendance current truth

Attendance 只拥有考勤业务真相。Telegram transport、Bot Token、update 获取、webhook、commands/menu、callback/inline answer 与消息发送全部由 UXAssistant Gateway 拥有。

## Public interfaces

- `POST /integration/gateway/v1/events`：接收 Gateway V1 事件，按 `eventId` 持久化确定性结果。
- `shift_web_app.py`：班表 WebApp；先原子消费 audience 为 `ATTENDANCE`、purpose 为 `PROVIDER_SESSION_EXCHANGE` 的短期 Gateway token，再签发一小时的 Attendance 自有 opaque session。Gateway `sessionId` 只允许消费一次；数据库只保存 Provider token hash。
- `gateway_provider/entrypoint.py`：Provider 生产入口。

Gateway 文件只通过 `GET /internal/v1/telegram-files/{fileRef}` 读取。Attendance 不保存或使用 Telegram `file_id` 作为网络凭据，不调用 Telegram API。

## Business truth

当前 V1 拥有注册、个人统计、群签到/签退、群离岗/返岗、考勤导出、班表与 Google Sheets 同步规则。已停用的 leave application、temporary leave approval、QC 与 legacy notification 不属于当前产品，代码已删除；历史内容只从 git 恢复。

## Database ownership

`migrations/0003_gateway_provider.sql` 到 `migrations/0011_worker_action_dependencies.sql` 定义空库可重复执行的 Provider schema、注册状态、WebApp session、terminal delivery receipt、Provider action worker、durable scheduler 和打卡后 Sheets outbox。迁移使用 immutable checksum 与 advisory lock；重复执行为 no-op，已应用 SQL 变化时 fail closed。Attendance 只连接 `ATTENDANCE_DATABASE_URL`；Provider 请求、WebApp 请求与后台 worker 均在该数据库作用域内执行。禁止跨库读取和运行时 fallback。

## Security boundaries

- Gateway → Attendance 与 Attendance → Gateway 使用不同 service credential。
- WebApp session 使用独立签名 secret，固定 issuer、audience、subject、expiry 和 session ID。
- Attendance 进程发现任何 Telegram owner credential 时拒绝启动。
- canonical protocol 只存在于 UXAssistant-Gateway `contracts/v1`；本仓库仅保留本地严格验证实现。
- `/readyz` 只检查 Attendance 自有数据库、必需表和 terminal receipt operational state；`PERMANENTLY_FAILED` 或 `UNCERTAIN` receipt 会使 readiness fail closed，不读取 Gateway transport truth。

## Durable Provider worker

当前群考勤摘要、每日 CSV 与 Google Sheets 班表同步由独立的
`python -m tasks.provider_scheduler` 进程调度。每个时间窗口先通过
`attendance_worker_schedule_runs` 持久 claim/lease/retry；摘要和日报再写入稳定
owner key 的 `attendance_worker_actions`。QC、audit 与 legacy notification 不会由该
调度器恢复。日报和摘要以已完成日期为游标顺序补跑遗漏日期；长时间 Sheets/报表操作
通过 lease heartbeat 续租，并用递增 `lease_version` fencing token 阻止失效 worker
提交结果。

成功打卡与其启用的 Test/BBQ Sheets 同步任务在同一数据库事务中提交。同步 worker 只在
事务提交后读取任务，使用稳定 run key、lease、60 秒重试和显式
`ATTENDANCE_DATABASE_URL`；进程退出后可恢复，重复 tick 不会重复执行已完成任务。用户可见
的打卡进度与成功文案不受该可靠性机制影响。

Attendance 后台动作再由独立的
`python -m tasks.provider_worker` 进程通过 Gateway
`POST /internal/v1/actions` 公共契约投递。worker 使用 PostgreSQL
`FOR UPDATE SKIP LOCKED`、带时限 lease 和持久 attempt 记录；进程崩溃后继续投递同一
`actionId`，只有 Gateway terminal receipt 才能把业务动作置为 delivered、retrying、
undeliverable 或 uncertain。Provider HTTP 进程与 worker 都不得持有 Telegram owner
credential。

同一延迟交互的终态动作按 `predecessor_action_id` 串行投递：后继只在前驱收到
`DELIVERED` 后才可 claim；前驱进入 `UNDELIVERABLE` 或 `UNCERTAIN` 时，所有未投递后继
持久转为 `PREDECESSOR_FAILED`，不得继续清理进度消息。进度动作尚无 receipt 时调度继续
等待；一旦收到任何非 `DELIVERED` 终态，调度原子转为 `FAILED`，停止业务工作并由
`/readyz` fail closed 暴露。

`POST /integration/gateway/v1/events` 的并发 lease 冲突返回可重试的 HTTP 503
`EVENT_BUSY` 和 `Retry-After: 1`。它不是业务拒绝；Gateway 必须用同一 `eventId` 重试，
不得将合法 Attendance 事件直接 dead-letter。
