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

`migrations/0003_gateway_provider.sql` 和 `migrations/0004_registration_provider.sql` 定义空库可重复执行的 Provider schema。Attendance 只连接 `ATTENDANCE_DATABASE_URL`；Provider 请求与 WebApp 请求均在该数据库作用域内执行。禁止跨库读取和运行时 fallback。

## Security boundaries

- Gateway → Attendance 与 Attendance → Gateway 使用不同 service credential。
- WebApp session 使用独立签名 secret，固定 issuer、audience、subject、expiry 和 session ID。
- Attendance 进程发现任何 Telegram owner credential 时拒绝启动。
- canonical protocol 只存在于 UXAssistant-Gateway `contracts/v1`；本仓库仅保留本地严格验证实现。
