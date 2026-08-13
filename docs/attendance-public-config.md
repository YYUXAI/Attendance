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

公开 manifest 保存群策略、AI/调度/WebApp/Sheets 功能开关、模型名、timeout、lease、batch、时区和日志级别。

Attendance 数据库保存 roster、员工例外、镜像员工、统计排除名单、Gateway 观察到的群 ID/route 与四个运行组件的配置指纹。群 ID 是公开诊断信息，但不是人工配置源。

root-only logical binding 保存数据库连接、Gateway 双向 bearer、WebApp signing secret、AI key、Google Service Account 以及全部 Spreadsheet/GID/Sheet title。功能关闭时不要求无关 binding；功能开启而 binding 缺失时进程拒绝启动。源码默认对象、checkout secret 和 `.env` fallback 均不允许。

## Candidate、激活与检查

先验证 redacted candidate：

```bash
ux test config --redacted --json
```

该输出应显示 candidate/active Attendance 业务配置、projection 状态、runtime fingerprint 与 drift，且不显示凭据或 Sheet 对象标识。

群列表变化同时影响 Gateway 分类和 Attendance，需由 Shawn/root 在全局锁与源码指纹保护下执行：

```bash
ux test restart all
```

不改变群路由的 Attendance 内部参数只需：

```bash
ux test restart attendance
```

普通 `ux` 开发者只能通过固定 dispatcher 执行上述精确测试 restart；不能直接调用 Docker、Compose、root controller 或 rollback。无效 candidate、缺失 private binding、active projection 不匹配或任一 Provider/WebApp/scheduler/worker 指纹漂移均 fail closed。

## 当前测试群

当前 candidate 声明一个群：`ux助手考勤测试群`，使用 `main` roster 与 `standard-checkin`。active 状态必须以 `ux test config --redacted --json` 和受控激活后的 runtime drift 为准；文档不是运行真相。

## 尚未迁移

此接口已经覆盖当前长期运行的群级能力。历史导入/诊断脚本仍属于一次性维护工具，不是运行配置源；它们只能在显式注入 root-only 对象 binding 后运行。新增能力必须先归类为 group capability、全局 Attendance 配置、数据库业务事实或 root-only private binding，不能新增 chat-ID/title 环境变量。
