# Attendance 统一配置维护指南

共享测试环境的唯一公开配置源是：

`/srv/ux/workspaces/shared/UXAssistant-Gateway/config/runtime-public.test.yaml`

Attendance 配置位于 `components.attendance`。不要修改 Compose、active projection、checkout `.env`，也不要填写 Telegram chat ID 或 routeKey；candidate/active projection 和运行时环境均由控制面生成。

## 群配置

`groups` 支持 0、1 或多个群。每个 title 必须唯一，并与 Telegram 当前群名完全一致。private group 与 public group 使用同一配置方式；public username 不是识别条件。

```yaml
components:
  attendance:
    groups:
      - title: ux助手考勤测试群
        roster: main
        capabilities:
          - standard-checkin
```

删除一项并受控 restart 后，旧绑定因配置指纹变化而不再 active。普通助手群不要加入此列表；Bot 加入普通群不需要 Attendance 配置。

可用 roster：

- `main`
- `alt`

可用 capability：

- `standard-checkin`
- `premium-ai`
- `remote-diff-checkin`
- `employee-id-only-checkin`
- `pc-only-screenshot`
- `visible-texts-identity-correction`
- `ai-dry-run-no-persist`
- `test-group-google-sheets`
- `bbq-google-sheets`
- `leave-mutual-exclusion`
- `leave-back-copy-fallback`
- `export-scope`

省略 capability 或给空列表时采用 `standard-checkin`。未知/重复 capability、重复 title、未知 roster 及冲突组合会拒绝 candidate；例如 `standard-checkin + remote-diff-checkin`、`test-group-google-sheets + bbq-google-sheets` 均不允许。

## 数据归属

公开 manifest 保存群策略、AI/调度/WebApp/Sheets 功能开关、Spreadsheet ID、GID、Sheet title、模型名、timeout、lease、batch、时区和日志级别。`%ux` 可直接新增、修改或删除这些值。

Attendance 数据库保存 roster、员工例外、镜像员工、统计排除名单、Gateway 观察到的群 ID/route 与四个运行组件的配置指纹。群 ID 是公开诊断信息，但不是人工配置源。

数据库角色密码、Gateway 双向 bearer、WebApp signing secret、AI key 与 Google Service Account 是 test-only 应用凭据，统一位于 `%ux` 可完整 CRUD 的 `/srv/ux/environments/test/ux-assistant/secrets/ux-extensions`。功能开启而所需凭据缺失时激活或进程启动会明确失败，不会静默关闭功能。OpenAI 真实 Key、Telegram 个人用户 session 和其他宿主受保护凭据不属于该目录。

## Candidate、激活与检查

先验证 redacted candidate：

```bash
ux test config --redacted --json
ux test config validate
ux test config diff --json
```

该输出应显示 candidate/active Attendance 业务配置、Sheet 对象标识、projection 状态、runtime fingerprint 与 drift，且不显示凭据值。

任意 `%ux` 成员都可在全局锁与源码指纹保护下原子激活公开 manifest：

```bash
ux test config apply
```

该命令校验 private binding、保存 previous config、生成 active projection，并执行匹配的 `restart all`；失败时恢复原 config/image 组合。不得先手工复制 projection 再 restart。

只修改 Attendance 源码、未改变公开 manifest 时，任意 `%ux` 成员执行：

```bash
ux test restart attendance
```

`%ux` 可执行 config apply、verify、restart、rollback，并可通过 `/run/ux-rootless/docker.sock` 完整控制专用测试 daemon；rootful Docker、`/run/docker.sock` 与 root controller 仍不可直接调用。无效 candidate、缺失应用凭据、active projection 不匹配或任一 Provider/WebApp/scheduler/worker 指纹漂移均 fail closed。

## 当前测试群

当前 candidate 声明一个群：`ux助手考勤测试群`，使用 `main` roster 与 `standard-checkin`。active 状态必须以 `ux test config --redacted --json` 和受控激活后的 runtime drift 为准；文档不是运行真相。

`ux助手考勤测试群` 在代码层固定启用与正式考勤测试群一致的 **AI 识图试跑（不入库）**：注册员工若不在当月 `main` 班表，走完整识图校验并返回可读结果，但不写入 `clock_records`；在班表内则正常入库。试跑识图 **直接走智谱 glm-4v-flash**，跳过 OCR.space，也不使用 premium glm-4.6v。该行为不依赖 `ai-dry-run-no-persist` capability（与 `test-group-google-sheets` 可并存于不同群，本群仅 standard-checkin 即可）。

## 尚未迁移

此接口已经覆盖当前长期运行的群级能力。历史导入/诊断脚本仍属于一次性维护工具，不是运行配置源。新增能力必须先归类为 group capability、公开 Attendance 配置、数据库业务事实、test-only 应用凭据或宿主受保护凭据，不能新增 chat-ID/routeKey 环境变量。
