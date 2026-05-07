# 状态机定义

⚠️ 本文件可能不是最新口径，请以 docs00_system_truth.md 为唯一真相入口

---

# 一、申请状态

SUBMITTED
APPROVING
APPROVED
REJECTED
CANCELLED
EFFECTIVE
COMPLETED
EXPIRED

流转：

SUBMITTED → APPROVING  
APPROVING → APPROVED / REJECTED  
APPROVED → EFFECTIVE  
EFFECTIVE → COMPLETED  

---

# 二、审批任务

## 执行状态（task_status）

PENDING
PROCESSING
APPROVED_DONE
REJECTED_DONE
FAILED
AUTO_SKIPPED
CANCELLED

说明：
- `APPROVED_DONE / REJECTED_DONE` 为一期历史兼容状态
- 审批最终业务结论必须以 `approval_result` 为准

## 业务结果（approval_result）

APPROVED
REJECTED
SKIPPED
NONE

---

# 三、审计任务

## 执行状态（task_status）

PENDING
PROCESSING
DONE
FAILED
SKIPPED
CANCELLED

## 业务结果（audit_result）

NORMAL
LATE
EARLY_LEAVE
ABSENT
ON_LEAVE
TEMPORARY_LEAVE
EXEMPT
NONE

---

## 审计阶段（audit_stage）

CHECKIN
CHECKOUT

说明：
- schema 当前可能保留 BREAK 枚举
- 当前业务状态机只使用 CHECKIN / CHECKOUT
- BREAK 不属于当前版本有效阶段

# 四、质检任务

## 字段分工（强约束）

* **执行状态**：`qc_task_queue.status` — 表示流程走到哪一步（含超时、取消等过程终态）。
* **业务结果**：`qc_task_queue.task_result` — 表示本条任务上的业务判定（与 `status` 不得混为一谈）。
* **最终结果表**：`qc_results.result` / `qc_results.attachment_id` — 仅记录该员工在该 `qc_date + shift_id + qc_round` 下的**最终**质检结论与附件；过程态不得写入 `qc_results`。

## 过程态时间与候选附件（与 docs02 一致）

* `first_private_notify_sent_at`：首条质检私信**成功发出**时间（UTC），写入后**不刷新**；用于「已送达任务」的 15 分钟硬期限计时起点。
* `created_at`：任务创建时间（UTC）；用于「未送达任务」的 15 分钟硬期限兜底计时起点（见下方 TIMEOUT 规则）。
* `pending_confirm_file_id`：待二次确认的**候选** Telegram `file_id`，可被新的有效上传**覆盖**；**仅**在二次确认通过后，才把最终附件写入 `qc_results.attachment_id`。

## 中间附件规则（强约束）

* 用户上传后、二次确认通过前：附件只存在于 `qc_task_queue.pending_confirm_file_id`（及交互层瞬时展示），**不得**提前写入 `qc_results.attachment_id`。

## 执行状态（status）

PENDING  
NOTIFIED  
WAITING_SUBMISSION  
SUBMITTED  
PROCESSING  
COMPLETED  
TIMEOUT  
FAILED  
CANCELLED  
SKIPPED  

## 业务结果（task_result）

PASS  
FAIL  
TIMEOUT  
EXEMPT  
INVALID_ATTACHMENT  
NONE  

---

## 交互与流转规则（强约束）

### 1. 首次【取消】（流程前期：未进入或未通过二次确认）

* 语义：用户拒绝配合本轮质检（首轮操作中的取消）。
* **失败终态（固定口径）**：
  - `qc_task_queue.status = CANCELLED`
  - `qc_task_queue.task_result = FAIL`
  - 并写入 `qc_results.result = FAIL`
* **不得**将首次取消与「二次确认阶段取消」混同。

### 2. 二次确认阶段【取消】

* 语义：用户已上传候选附件，在二次确认界面选择取消。
* **不记失败**：不改变「本轮最终失败」结论（不触发首次取消的失败终态语义）。
* **回退**到等待上传（例如回到 `WAITING_SUBMISSION` 或文档与实现约定的等价状态），允许重新上传；**以最后一次有效附件为准**的语义仍通过更新 `pending_confirm_file_id` 实现。
* **不刷新总超时**：**不得**改写 `first_private_notify_sent_at`；15 分钟总窗口仍从首条私信成功时刻起算。

### 3. TIMEOUT

**统一收口口径（15 分钟硬期限，必须严格执行）：**

1. 已送达任务（进入 NOTIFIED / WAITING_SUBMISSION / SUBMITTED 等阶段）：
   - 超时起点 = `first_private_notify_sent_at`
   - 截止时间 = `first_private_notify_sent_at` + 固定 15 分钟

2. 未送达任务（仍处于 PENDING 且 `first_private_notify_sent_at` IS NULL）：
   - 超时兜底起点 = `created_at`
   - 截止时间 = `created_at` + 固定 15 分钟

3. 到期后的收口结果（两类任务一致）：
   - `qc_task_queue.status = TIMEOUT`
   - `qc_task_queue.task_result = TIMEOUT`
   - 并按实现尽量写入 `qc_results.result = TIMEOUT`（若组织绑定缺失则允许仅收口任务表并记录日志）

**目的：**
- 保证单轮必收口（进入 `qc_task_queue` 后不得长期悬挂在非终态）
- 保证未送达 = 未完成（单轮完结公告与班次汇总公告均应将其归入未完成）
- 保证单轮完结公告不会因 PENDING 悬挂而不触发

* 由 **worker / 轮询**依据上述规则与固定时长**主动判定**并落库（`status` / `task_result` 与 `qc_results` 以 docs02 为准）。
* **禁止**仅依赖用户在 handler 内操作才触发超时。

### 4. 二次确认【确认】通过

* 本轮质检完成：将最终 `file_id` 写入 `qc_results.attachment_id`，并写入 `qc_results.result` 等最终结果字段；`qc_task_queue` 进入完成类终态，`task_result` 与 `status` 与 docs02 保持一致。

---

# 五、通知任务

## 执行状态（task_status）

PENDING
PROCESSING
RETRYING
CANCELLED
SKIPPED
DONE

## 业务结果（delivery_result）

SENT
FAILED
UNDELIVERABLE
NONE

---

## 通知任务流转规则（强约束）

PENDING → PROCESSING  
👉 worker 抢占任务

PROCESSING → DONE  
👉 发送成功（delivery_result = SENT）

PROCESSING → RETRYING  
👉 发送失败但可重试（delivery_result = FAILED）

RETRYING → PROCESSING  
👉 进入下一次发送尝试

RETRYING → DONE  
👉 达到最大重试次数（delivery_result = UNDELIVERABLE）

PROCESSING → DONE  
👉 判定不可送达（delivery_result = UNDELIVERABLE）

---

## 发送结果判定规则（强约束）

SENT  
👉 成功发送

FAILED  
👉 临时失败（可重试）  
例如：
- 网络异常
- Telegram 超时
- 短暂 API 错误

UNDELIVERABLE  
👉 不可送达终态（不可重试）  
例如：
- 用户未与 bot 建立私聊
- bot 被用户拉黑
- chat 不存在 / 无效
- 用户账号异常

NONE  
👉 尚未执行发送

---

## 重试规则（强约束）

- retry_count 每次发送失败后 +1
- retry_count < 3 → 进入 RETRYING
- retry_count ≥ 3 → DONE + UNDELIVERABLE

---

# 六、事件日志

CREATED
DISPATCHED
PROCESSED
FAILED
IGNORED

---

# 七、全局规则（强约束）

必须遵守：

1. 状态 ≠ 结果
2. 状态表示流程进度
3. 结果表示最终判定
4. 任务表 ≠ 结果表

---

# 八、禁止行为

禁止：

* 将结果字段写入状态集合
* 使用状态字段表达业务结论
* 在状态机中混用状态与结果

---

# 九、设计原则

* 所有任务表必须拆分：执行状态 + 业务结果
* 状态机只描述流程推进，不描述最终结论
* 最终结论必须落在结果字段或结果表中