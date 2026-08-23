# UX 测试栈 · `config apply` 检查清单

> 适用：需要**全栈配置投影生效**时（例如 primary 班表换源、新考勤群挂路由、Gateway/OmniAI 绑定变更）。  
> 日常只改 Attendance/Gateway **源码** → 用 `ux test restart <component>`，**不要** apply。

服务器：`ssh my-work-nayxua`  
配置根：`/srv/ux/environments/test/ux-assistant/config/`  
Active 投影：`config/active/projections/attendance.env`、`config/active/runtime-public.yaml`

---

## 0. 先判断：要不要 apply？

| 场景 | 做法 |
|------|------|
| 只改了 Attendance / Gateway **Python/TS 源码** | `ux test restart attendance` 或 `restart gateway` |
| 改了 **`runtime-public.yaml`**（班表 primary、群路由、publicBaseUrl 等） | **需要 `config apply`** |
| 只改了 **手工写库**（一次性 sync） | 数据在库里，但**定时 sync 仍按旧配置** → 要永久生效必须 apply 换源 |
| 栈红 / recovery-failed / 肖恩 private-ai 在跑 | **停手**，不 apply |

---

## 1. 执行前 · 锁与栈（必做）

在服务器依次执行，**任一项不通过则停手**：

```bash
# 1.1 栈状态 — 目标组件均应 running + healthy（scheduler/worker 可为 none）
ux test status

# 1.2 肖恩 private-ai 是否在跑（Shawn-only 锁）
ux test private-ai status
ps aux | grep -E 'ux test private-ai|ux-private-ai-real-telegram' | grep -v grep
```

**通过标准：**

- [ ] `gateway-real` → healthy  
- [ ] `omniai-provider` / `omniai-webapp` → healthy  
- [ ] `attendance-provider` / `attendance-webapp` → healthy  
- [ ] `webapp-edge` → healthy  
- [ ] **无** `recovery-failed` / 大面积 not-running  
- [ ] **无** 活跃的 `ux test private-ai …` 进程（有则等肖恩跑完或确认可打断）

---

## 2. 配置改动确认（apply 前写好）

### 2.1 班表 primary 换源（工号打卡群 · 当前待办）

编辑 **`config/runtime-public.yaml`**（或 workspace 镜像后同步到服务器），确认：

```yaml
sheets:
  primary:
    spreadsheetId: 10RTURqDJqSEmaTQxl6dQU_Sc5zZlH-Wg92zrdDy9xsw
    sheetGid: 921744520          # tab「排班 2026-08」
  # yearMonth 等与 tab 一致，例如 2026-08
```

**不要**再指向旧表：

- ~~`1BD6PeaCdiavNiynK8Dp2e5kqYSHT-tPle5brn-2LSiU`~~  
- ~~gid `757170338`~~

- [ ] spreadsheetId / sheetGid / yearMonth 三项一致  
- [ ] 新表已共享给 UX 栈 Google 服务账号（scheduler 容器有 `/run/secrets/google_service_account`）  
- [ ] 未误改 BBQ / remoteDiff / testGroup 等 **无关 profile**（除非本次就是要改）

### 2.2 其它常见 apply 项（按需勾选）

- [ ] 新增/修改 `attendanceGroups` 群路由与 chat_id  
- [ ] `publicBaseUrl` / shift web 地址  
- [ ] Gateway ↔ Provider bearer 绑定（一般不动）

---

## 3. 校验（apply 前）

```bash
cd /srv/ux/environments/test/ux-assistant   # 若 ux 命令已全局则直接执行

ux test config validate
ux test config diff          # 可选：人工过一眼 primary / 群 / env 投影
```

- [ ] `validate` 通过，无 schema / 必填项报错  
- [ ] `diff` 里 **只有本次预期变更**（尤其 `GOOGLE_SHEETS_SPREADSHEET_ID`、`GOOGLE_SHEETS_SHEET_GID`）

预期 diff 片段示例：

```text
GOOGLE_SHEETS_SPREADSHEET_ID=10RTURq…
GOOGLE_SHEETS_SHEET_GID=921744520
```

---

## 4. 执行 apply

```bash
ux test status    # 再查一次，仍全绿
ux test config apply
ux test status    # apply 后立即复查
```

- [ ] apply 命令 exit 0 / 无 recovery-failed  
- [ ] apply 后各组件仍 healthy（OmniAI 若短暂重启，等 1～2 分钟再查）

**禁止：**

- 不要用 `ux test restart all` 代替 apply  
- 不要栈红时连点 restart「碰运气」  
- 不要 apply 后向 Telegram 群**擅自**发开班/概览/验证消息  

---

## 5. apply 后 · 后台验证（不发群）

### 5.1 配置已投影

```bash
rg 'GOOGLE_SHEETS_SPREADSHEET|GOOGLE_SHEETS_SHEET_GID' \
  /srv/ux/environments/test/ux-assistant/config/active/projections/attendance.env
```

- [ ] active 里已是新 spreadsheetId / gid  

### 5.2 班表 sync（scheduler 有 SA）

```bash
ux test logs-safe attendance --since 30m --tail 80 | grep -i google
```

或手动触发一次 sync 脚本（若栈内有 documented 命令），在**服务器/日志**看结果：

- [ ] sync 成功、人数与预期接近（例如工号群 roster 人数）  
- [ ] **未**再出现从旧表 `1BD6Pea…` 同步的日志  

### 5.3 `/start` 与私聊（仅自己账号测，可选）

- [ ] 自己私聊 `/start` 首页正常（非「首页暂时不可用」）  
- [ ] 未绑定用户无底部「考勤菜单」；绑定后有  

### 5.4 数据库抽查（可选）

```bash
# 示例：查工号群相关 roster 是否仍在
echo "SELECT count(*) FROM employee_shift_roster;" | ux test db attendance
```

---

## 6. 失败时怎么处理

| 现象 | 动作 |
|------|------|
| apply 前 `status` 有红 | **不 apply**，报状态，找肖恩 |
| private-ai 进程在跑 | **等结束**或确认后再 apply |
| apply 后 OmniAI 短暂不可用 | 等 1～2 分钟再 `/start`；仍失败查 gateway / omniai 日志 |
| sync 仍读旧表 | 查 active `attendance.env` 是否未更新；必要时 `config diff` 复核 yaml |
| recovery-failed | **停手**，不反复 rollback/restart，找肖恩 |

---

## 7. 本次工号群切源 · 快速抄录

| 项 | 值 |
|----|-----|
| 群 | UX 工号打卡群 `-5414689501` |
| 新 Spreadsheet | `10RTURqDJqSEmaTQxl6dQU_Sc5zZlH-Wg92zrdDy9xsw` |
| 新 gid | `921744520`（排班 2026-08） |
| 旧 Spreadsheet（停用） | `1BD6PeaCdiavNiynK8Dp2e5kqYSHT-tPle5brn-2LSiU` / gid `757170338` |
| 同步间隔 | `GOOGLE_SHEETS_SYNC_INTERVAL_SECONDS=14400`（4h） |

**一句话：** 手工 sync 只写库一次；**apply 换 primary 后**，定时任务才会永久从你的表拉，不再走旧表。

---

## 8. 与日常 restart 的分工（备忘）

| 改动类型 | 命令 |
|----------|------|
| Attendance 源码（打卡/OCR/菜单等） | `ux test restart attendance` |
| Gateway 源码（/start 键盘等） | `ux test restart gateway` |
| `runtime-public.yaml` / 班表源 / 群路由 | **`ux test config apply`**（本清单） |
