# 数据库结构说明（按当前 DDL 版本）

⚠️ 本文件不是最高优先级真相文件
如与 `docs00_system_truth.md` 冲突，以 `docs00_system_truth.md` 为准。

---

# 一、文档用途

本文件用于给开发者与 Cursor 提供数据库层面的统一事实来源。

使用规则：

* 表结构、字段名、唯一约束、外键、CHECK 约束，以当前 DDL 为准
* 本文件用于解释“每张表是什么、字段是什么意思、约束为什么这样设计”
* 如果 DDL 与本文件冲突，以 DDL 为准，并同步更新本文件
* 如果本文件与 `docs00_system_truth.md` 冲突，以 `docs00_system_truth.md` 为准

---

# 二、全局规则

## 1. 全系统统一业务标识

* 全系统统一业务标识：`employee_id`
* 除技术主键 `id` 外，大多数业务关联应优先基于 `employee_id`

## 2. 时间规则

* 数据库存储统一使用 UTC
* 展示层与业务判定需要按班次时区转换
* 业务时间段字段如 `start_at` / `end_at` 在数据库中仍为 UTC 存储，只是语义上表示业务时段

## 3. 分表原则

本系统表分为以下几类：

* 配置表：组织、班次、管理员、固定免检名单
* 身份表：注册信息
* 事实表：打卡原始记录、申请原始记录
* 生效表：审批通过后的拆分结果或生效时段
* 派生表：基于生效事实衍生出的业务辅助表
* 结果表：审计结果、质检结果
* 任务队列表：审批、审计、质检、通知
* 日志表：事件日志

## 4. 任务表统一原则

所有任务类表必须区分：

* 执行状态：流程走到哪一步
* 业务结果：最终判定为何种结果

二者不得混用。

## 5. 外键默认行为

当前 DDL 的外键口径统一为：

* `ON DELETE RESTRICT`
* `ON UPDATE CASCADE`

## 6. 时区枚举

`shifts.timezone` 当前只允许以下值：

* `Asia/Shanghai`
* `Asia/Kuala_Lumpur`
* `Asia/Bangkok`
* `Asia/Dubai`

---

# 三、表清单总览

## 配置类

* `organizations`
* `shifts`
* `qc_exemption_fixed_list`
* `admin_list`

## 身份类

* `registrations`

## 原始事实类

* `leave_applications`
* `temporary_leave_applications`
* `clock_records`

## 生效数据类

* `effective_leave_days`
* `effective_temporary_leaves`

## 派生数据类

* `temporary_qc_exemption_list`

## 结果类

* `audit_results`
* `qc_results`

## 日志与任务类

* `event_logs`
* `approval_task_queue`
* `audit_task_queue`
* `qc_task_queue`
* `notification_queue`

---

# 四、逐表字段说明

# 1. organizations

## 作用

组织表。定义部门结构及负责人信息。

## 主键

* `id`

## 字段

* `id`：技术主键
* `department_name`：部门名称
* `highest_responsible_employee_id`：最高负责人 employee_id
* `leader_employee_id`：直属负责人 employee_id

## 说明

* 本表只存组织信息与负责人标识
* 负责人字段当前是 employee_id 文本，不是直接外键到 `registrations`
* 这是有意保留的弱引用设计，允许组织配置先于人员注册存在

---

# 2. shifts

## 作用

班次表。定义考勤规则与质检触发规则。

## 主键

* `id`

## 字段

* `id`：技术主键
* `checkin_time`：班次上班时间
* `checkout_time`：班次下班时间
* `timezone`：班次时区
* `is_overnight`：是否跨夜班次
* `attendance_group_id`：考勤群组 ID
* `qc_trigger_interval`：质检触发间隔
* `qc_draw_count`：每轮抽查人数
* `qc_example_file_id`：质检示例附件 file_id
* `attendance_flex_interval`：打卡弹性时间
* `max_late_early_tolerance`：迟到早退容忍时间
* `qc_enabled`：是否启用质检

## CHECK 约束

* `timezone` 只能是允许的 4 个时区之一

## 说明

* `attendance_group_id` 用于把班次和 TG 考勤群做绑定
* 迟到、早退、打卡窗口、质检抽查，都依赖本表配置
* `is_overnight` 只表示班次是否跨自然日，不单独定义业务日期归属；业务日期归属以 `docs00_system_truth.md` 为准

---

# 3. registrations

## 作用

注册信息表。记录员工基础信息及 Telegram 绑定关系，是全系统身份源。

## 主键

* `id`

## 业务键

* `employee_id`

## 字段

* `id`：技术主键
* `employee_id`：员工业务编号，全系统唯一
* `tg_id`：Telegram 用户唯一标识，全系统唯一
* `english_name`：员工英文名
* `registered_at`：注册时间（UTC）
* `registered_chat_id`：注册发生的聊天窗口 ID
* `tg_username`：Telegram 用户名
* `organization_id`：所属组织 ID
* `shift_id`：所属班次 ID

## 唯一约束

* `employee_id` 唯一
* `tg_id` 唯一

## 外键

* `organization_id -> organizations.id`
* `shift_id -> shifts.id`

## 说明

* 所有外部业务表统一优先通过 `employee_id` 关联
* `id` 仅为内部技术主键，不作为主业务标识传播

---

# 4. admin_list

## 作用

管理员名单。配置系统管理员权限，用于测试、干预和管理能力。

## 主键

* `id`

## 字段

* `id`：技术主键
* `admin_employee_id`：管理员 employee_id

## 唯一约束

* `admin_employee_id` 唯一

## 外键

* `admin_employee_id -> registrations.employee_id`

## 说明

* 当前口径是不再使用 `registration_id`
* 管理员权限绑定到 `employee_id`

---

# 5. leave_applications

## 作用

休假申请原始记录表。记录员工提交的休假申请，不论是否审批通过都保留完整记录。

## 主键

* `id`

## 字段

* `id`：技术主键
* `employee_id`：申请员工 employee_id
* `organization_id`：申请时所属组织
* `shift_id`：申请时所属班次
* `start_at`：休假开始时间
* `end_at`：休假结束时间
* `leave_reason`：休假原因
* `remark`：申请备注
* `status`：申请状态
* `completed_at`：流程完成时间
* `created_at`：申请创建时间

## 外键

* `employee_id -> registrations.employee_id`
* `organization_id -> organizations.id`
* `shift_id -> shifts.id`

## CHECK 约束

`status` 允许值：

* `SUBMITTED`
* `APPROVING`
* `APPROVED`
* `REJECTED`
* `CANCELLED`
* `EFFECTIVE`
* `COMPLETED`
* `EXPIRED`

## 索引重点

* `employee_id`
* `organization_id`
* `shift_id`
* `(start_at, end_at)`
* `status`

## 说明

* 本表是原始申请单，不是最终生效事实
* 审批通过后，需要进一步写入生效表
* 申请单状态表达业务状态，不表达系统故障

---

# 6. temporary_leave_applications

## 作用

离岗申请表。记录员工临时离岗报备申请，用于影响质检与审计判定。

## 主键

* `id`

## 字段

* `id`：技术主键
* `employee_id`：申请员工 employee_id
* `organization_id`：申请时所属组织
* `shift_id`：申请时所属班次
* `start_at`：离岗开始时间
* `end_at`：离岗结束时间
* `leave_reason`：离岗原因
* `remark`：申请备注
* `status`：申请状态
* `completed_at`：流程完成时间
* `created_at`：申请创建时间

## 外键

* `employee_id -> registrations.employee_id`
* `organization_id -> organizations.id`
* `shift_id -> shifts.id`

## CHECK 约束

`status` 允许值与休假申请一致：

* `SUBMITTED`
* `APPROVING`
* `APPROVED`
* `REJECTED`
* `CANCELLED`
* `EFFECTIVE`
* `COMPLETED`
* `EXPIRED`

## 索引重点

* `employee_id`
* `organization_id`
* `shift_id`
* `(start_at, end_at)`
* `status`

## 说明

* 本表是原始离岗申请
* 审批通过后进入 `effective_temporary_leaves`
* 后续还会影响 `temporary_qc_exemption_list`

---

# 7. clock_records

## 作用

打卡记录表。记录员工打卡行为原始事实，作为审计依据。

## 主键

* `id`

## 字段

* `id`：技术主键
* `chat_id`：打卡发生的聊天窗口 ID
* `file_id`：打卡证据文件 ID
* `tg_id`：打卡人 Telegram ID
* `employee_id`：打卡员工 employee_id
* `shift_id`：对应班次 ID
* `clock_time`：打卡时间（UTC）

## 外键

* `employee_id -> registrations.employee_id`
* `shift_id -> shifts.id`

## 索引重点

* `clock_time`
* `employee_id`
* `(employee_id, clock_time)`
* `shift_id`
* `tg_id`

## 说明

* 本表只记录原始打卡事实
* 是否算有效打卡、是否迟到、是否缺卡，不在本表判断，而由审计流程判定

---

# 8. effective_leave_days

## 作用

已生效休假名单。将审批通过的休假拆分为“按工作日”的生效记录，用于审计判定。

## 主键

* `id`

## 字段

* `id`：技术主键
* `employee_id`：员工 employee_id
* `leave_date`：生效休假日期
* `shift_id`：关联班次
* `leave_reason`：休假原因
* `application_remark`：来源申请单备注
* `application_id`：来源休假申请 ID

## 唯一约束

* `(employee_id, leave_date, shift_id)` 唯一

## 外键

* `application_id -> leave_applications.id`
* `employee_id -> registrations.employee_id`
* `shift_id -> shifts.id`

## 说明

* 这是用于判定“某个工作日是否在休假中”的事实表
* 不是原始申请表
* `leave_date` 的业务解释以 `docs00_system_truth.md` 的工作日定义为准，不简单等于自然日

---

# 9. effective_temporary_leaves

## 作用

已生效离岗报备表。记录审批通过后实际生效的离岗时间段。

## 主键

* `id`

## 字段

* `id`：技术主键
* `employee_id`：员工 employee_id
* `effective_date`：生效日期 / 业务归属日期
* `shift_id`：关联班次
* `reason_remark`：离岗原因说明
* `leave_start_at`：离岗开始时间
* `leave_end_at`：离岗结束时间
* `application_id`：来源离岗申请 ID

## 唯一约束

* `(employee_id, leave_start_at, leave_end_at, shift_id, application_id)` 唯一

## 外键

* `application_id -> temporary_leave_applications.id`
* `employee_id -> registrations.employee_id`
* `shift_id -> shifts.id`

## 说明

* 本表用于表示真实生效的离岗时段
* 是 temporary leave 的真实生效事实来源
* 可同时支撑质检免检与审计判定
* 一切“离岗是否生效”的最终判断，都应回到本表

---

# 10. qc_exemption_fixed_list

## 作用

质检固定免检名单。配置固定不参与质检的人员。

## 主键

* `id`

## 字段

* `id`：技术主键
* `shift_id`：班次 ID
* `employee_id`：员工 employee_id
* `remark`：备注

## 唯一约束

* `(shift_id, employee_id)` 唯一

## 外键

* `employee_id -> registrations.employee_id`
* `shift_id -> shifts.id`

## 说明

* 这是长期静态免检名单
* 与离岗触发的临时免检覆盖记录不同

---

# 11. temporary_qc_exemption_list

## 作用

离岗临时免检覆盖表。根据已生效离岗报备动态生成，用于质检模块判断员工在特定时间窗口内是否应被排除。

## 主键

* `id`

## 字段

* `id`：技术主键
* `shift_id`：班次 ID
* `employee_id`：员工 employee_id
* `work_date`：该免检记录归属的班次工作日
* `exemption_start_at`：免检开始时间（UTC）
* `exemption_end_at`：免检结束时间（UTC）
* `source_effective_temporary_leave_id`：来源已生效离岗记录 ID
* `updated_at`：更新时间

## 唯一约束

* `source_effective_temporary_leave_id` 唯一

## 外键

* `employee_id -> registrations.employee_id`
* `shift_id -> shifts.id`
* `source_effective_temporary_leave_id -> effective_temporary_leaves.id`

## CHECK 约束

* `exemption_start_at < exemption_end_at`

## 索引重点

* `(shift_id, work_date, employee_id)`
* `(shift_id, exemption_start_at, exemption_end_at)`
* `(employee_id, exemption_start_at, exemption_end_at)`

## 说明

* 本表是由 `effective_temporary_leaves` 派生出的质检辅助表
* 它不是“全天免检名单表”，而是“时间窗口覆盖表”
* 一条 `effective_temporary_leaves` 记录只允许派生一条临时免检覆盖记录
* 本表用于为质检模块提供“候选免检覆盖集合”与查询优化能力
* 质检模块不得仅凭本表存在记录就直接排除员工
* 质检模块最终是否排除员工，必须回到 `effective_temporary_leaves`，并按抽检时刻判断是否命中真实生效窗口
* 禁止仅凭 `work_date` 维度将员工整天全部排除
* 本表属于查询优化辅助表，不是最终真相源

---

# 12. audit_results

## 作用

审计结果表。记录员工考勤审计最终判定结果。

## 主键

* `id`

## 字段

* `id`：技术主键
* `employee_id`：员工 employee_id
* `shift_id`：班次 ID
* `organization_id`：组织 ID
* `audit_date`：审计日期
* `audit_stage`：审计阶段
* `checked_at`：实际审计执行时间
* `valid_clock_time`：被判定为有效打卡的时间
* `result`：审计结果

## 唯一约束

* `(employee_id, audit_date, audit_stage, shift_id)` 唯一

## 外键

* `employee_id -> registrations.employee_id`
* `organization_id -> organizations.id`
* `shift_id -> shifts.id`

## CHECK 约束

### audit_stage 允许值

* `CHECKIN`
* `CHECKOUT`
* `BREAK`

### result 允许值

* `NORMAL`
* `LATE`
* `EARLY_LEAVE`
* `ABSENT`
* `ON_LEAVE`
* `TEMPORARY_LEAVE`
* `EXEMPT`

## 说明

* 本表是“最终审计结果”
* 审计任务执行后，应幂等写入本表
* `valid_clock_time` 用于保留被认可的打卡依据
* schema 当前保留 `BREAK` 枚举作为兼容位
* 当前业务规则仅使用 `CHECKIN / CHECKOUT`
* `BREAK` 不属于当前版本有效审计阶段，未经 `docs00_system_truth.md` 更新不得启用

---

# 13. qc_results

## 作用

质检结果表。记录质检流程最终结果。

## 主键

* `id`

## 字段

* `id`：技术主键
* `employee_id`：员工 employee_id
* `shift_id`：班次 ID
* `organization_id`：组织 ID
* `qc_date`：质检日期
* `qc_round`：质检轮次
* `checked_at`：发起 / 检查时间
* `completed_at`：完成判定时间
* `result`：质检结果
* `attachment_id`：最终确认后写入的提交附件 ID（Telegram `file_id` 口径，与业务一致）

## 唯一约束

* `(employee_id, qc_date, shift_id, qc_round)` 唯一

## 外键

* `employee_id -> registrations.employee_id`
* `organization_id -> organizations.id`
* `shift_id -> shifts.id`

## CHECK 约束

`result` 允许值：

* `PASS`
* `FAIL`
* `TIMEOUT`
* `EXEMPT`

## 说明

* 本表只存最终结果
* 提交流程中的临时状态，应放在 `qc_task_queue`
* `attachment_id` 仅在员工完成「二次确认」且本轮质检业务结论落库时写入；二次确认前的候选附件只存在于 `qc_task_queue.pending_confirm_file_id`，不得提前写入本表

---

# 14. event_logs

## 作用

事件日志表。记录系统事件执行过程，用于日志、追踪、派发和重试诊断。

## 主键

* `id`

## 字段

* `id`：技术主键
* `event_name`：当前事件名称
* `related_event_name`：关联事件名称
* `result`：事件处理结果
* `related_event_id`：关联事件 ID
* `created_at`：事件创建时间
* `processed_at`：事件处理完成时间
* `retry_count`：重试次数
* `error_message`：失败信息

## CHECK 约束

`result` 允许值：

* `CREATED`
* `DISPATCHED`
* `PROCESSED`
* `FAILED`
* `IGNORED`

## 索引重点

* `created_at`
* `(event_name, result)`
* `(related_event_name, related_event_id)`

## 说明

* 本表明确不做幂等唯一约束
* 这是日志表，不是结果表
* `log_id` 用于表示一次具体触发动作，不应当被当作长期业务对象 ID

---

# 15. approval_task_queue

## 作用

审批任务队列表。驱动多级审批流程。

## 主键

* `id`

## 字段

* `id`：技术主键
* `application_type`：申请类型
* `application_id`：申请单 ID
* `application_submitted_at`：申请提交时间
* `approval_level`：审批层级
* `applicant_employee_id`：申请人 employee_id
* `approver_employee_id`：审批人 employee_id
* `task_status`：任务执行状态
* `approval_result`：审批结果
* `approved_at`：审批时间
* `approver_remark`：审批备注
* `task_created_at`：任务创建时间

## 唯一约束

* `(application_type, application_id, approval_level, approver_employee_id)` 唯一

## 外键

* `applicant_employee_id -> registrations.employee_id`
* `approver_employee_id -> registrations.employee_id`

## CHECK 约束

### task_status 允许值

* `PENDING`
* `PROCESSING`
* `APPROVED_DONE`
* `REJECTED_DONE`
* `AUTO_SKIPPED`
* `CANCELLED`
* `FAILED`

### approval_result 允许值

* `APPROVED`
* `REJECTED`
* `SKIPPED`
* `NONE`

## 说明

* `task_status` 表示审批任务跑到哪一步
* `approval_result` 表示审批结论
* 二者不能混用
* 当前 `task_status` 中包含 `APPROVED_DONE / REJECTED_DONE`，属于一期历史兼容状态设计
* 审批最终业务结论仍应以 `approval_result` 为准

---

# 16. audit_task_queue

## 作用

审计任务队列表。驱动考勤审计流程。

## 主键

* `id`

## 字段

* `id`：技术主键
* `log_id`：来源事件日志 ID
* `audit_started_at`：审计开始时间
* `employee_id`：目标员工 employee_id
* `target_date`：目标审计日期
* `audit_stage`：审计阶段
* `audit_result`：审计任务结果
* `created_at`：任务创建时间
* `processed_at`：任务处理时间
* `retry_count`：重试次数
* `error_message`：失败信息
* `task_status`：任务执行状态

## 唯一约束

* `(log_id, employee_id, target_date, audit_stage)` 唯一

## 外键

* `employee_id -> registrations.employee_id`
* `log_id -> event_logs.id`

## CHECK 约束

### task_status 允许值

* `PENDING`
* `PROCESSING`
* `DONE`
* `FAILED`
* `SKIPPED`
* `CANCELLED`

### audit_result 允许值

* `NORMAL`
* `LATE`
* `EARLY_LEAVE`
* `ABSENT`
* `ON_LEAVE`
* `TEMPORARY_LEAVE`
* `EXEMPT`
* `NONE`

### audit_stage 允许值

* `CHECKIN`
* `CHECKOUT`
* `BREAK`

## 说明

* 本表是任务过程，不是最终结果
* 最终结论应写入 `audit_results`
* schema 当前保留 `BREAK` 枚举作为兼容位
* 当前业务仅处理 `CHECKIN / CHECKOUT`
* `BREAK` 不属于当前版本有效审计阶段

---

# 17. qc_task_queue

## 作用

质检任务队列表。驱动质检通知、等待提交、二次确认、判定和超时处理；承载过程态时间与「待二次确认」候选附件，不承载最终质检业务结论（结论在 `qc_results`）。

## 主键

* `id`

## 字段

* `id`：技术主键
* `log_id`：来源事件日志 ID
* `employee_id`：目标员工 employee_id
* `shift_id`：班次 ID
* `qc_date`：质检日期
* `qc_round`：质检轮次
* `status`：任务执行状态
* `task_result`：任务结果
* `first_private_notify_sent_at`：首条质检私信**成功发出**时间（UTC）
* `pending_confirm_file_id`：当前待二次确认的**候选**附件标识（Telegram `file_id` 口径；可为空）
* `created_at`：任务创建时间
* `processed_at`：任务处理时间
* `retry_count`：重试次数
* `error_message`：失败信息

## 唯一约束

* `(log_id, employee_id)` 唯一

## 外键

* `employee_id -> registrations.employee_id`
* `shift_id -> shifts.id`
* `log_id -> event_logs.id`

## CHECK 约束

### status 允许值

* `PENDING`
* `NOTIFIED`
* `WAITING_SUBMISSION`
* `SUBMITTED`
* `PROCESSING`
* `COMPLETED`
* `TIMEOUT`
* `FAILED`
* `CANCELLED`
* `SKIPPED`

### task_result 允许值

* `PASS`
* `FAIL`
* `TIMEOUT`
* `EXEMPT`
* `INVALID_ATTACHMENT`
* `NONE`

## 字段语义（强约束）

### `first_private_notify_sent_at`

* 语义：**首次**向该员工成功发出本轮质检流程的**首条私信**（含示例与操作引导）的时刻；存储为 UTC。
* **不是**任务创建时间：不得用 `created_at` 代替。
* **不是**通用「最后处理时间」：不得用 `processed_at` 代替。
* 一经写入**不得再刷新**（不因状态回退、重试通知而改写）。
* 已送达任务的 **15 分钟硬期限**计时起点：截止时间 = 本字段 + 固定 15 分钟（业务常量，见实现）；**不得**从用户点击【确认】或上传附件起算。
* 未送达任务的 **15 分钟硬期限兜底起点**：若任务仍处于 `PENDING` 且 `first_private_notify_sent_at` 为空，则以 `qc_task_queue.created_at` 作为兜底计时起点（截止时间 = `created_at` + 固定 15 分钟），到期后也必须收口为 `TIMEOUT`（见 docs03）。
* 超时判定必须由 **worker / 轮询**依据上述规则主动落库，不得依赖 handler 被动触发。

### `pending_confirm_file_id`

* 语义：**当前**待二次确认的候选附件，对应用户最近一次**有效**上传（图片或文件均可能）；存 Telegram `file_id`。
* **不是**最终结果附件：最终附件仅写在 `qc_results.attachment_id`，且仅在二次确认通过后写入。
* **不是**历史附件列表：只保留**一条**当前候选；新的有效上传**覆盖**旧值。
* 二次确认【确认】通过后：应将最终 `file_id` 写入 `qc_results.attachment_id`，并视实现清空或不再依赖本字段；二次确认【取消】回退等待上传时，可保留或按规则清空本字段，但**不得**延长由 `first_private_notify_sent_at` 决定的 15 分钟总窗口。

## 说明

* 当前 DDL 的执行状态字段名是 `status`
* 当前 DDL 的结果字段名是 `task_result`
* 最终结果应写入 `qc_results`
* 同一 `log_id + employee_id` 只允许一条质检任务
* 新一轮质检应产生新的 `log_id`

---

# 18. notification_queue

## 作用

通知队列表。负责异步通知任务的消息发送、失败重试与不可达判定。

## 主键

* `id`

## 字段

* `id`：技术主键
* `log_id`：来源事件日志 ID
* `notify_tg_id`：通知目标 Telegram ID 或群 chat_id
* `template_id`：通知任务类型 ID
* `reply_content`：消息正文
* `attachment_id`：附件 ID
* `delivery_result`：投递结果
* `created_at`：任务创建时间
* `processed_at`：处理时间
* `retry_count`：重试次数
* `error_message`：失败信息
* `task_status`：任务执行状态

## 唯一约束

* `(log_id, notify_tg_id, template_id)` 唯一

## 外键

* `log_id -> event_logs.id`

## CHECK 约束

### task_status 允许值

* `PENDING`
* `PROCESSING`
* `RETRYING`
* `CANCELLED`
* `SKIPPED`
* `DONE`

### delivery_result 允许值

* `SENT`
* `FAILED`
* `UNDELIVERABLE`
* `NONE`

## 说明

* `task_status` 是发送任务流程状态
* `delivery_result` 是实际送达结论
* Telegram 无法主动私聊未开启会话用户时，应归入 `UNDELIVERABLE` 语义处理
* 对群公告类通知，`notify_tg_id` 也可承载群 `chat_id`
* 本表只承载异步通知任务，不承载 handler 内即时 reply / callback.answer
* `template_id` 是稳定通知语义枚举，不是文案模板 ID
* `reply_content` 必须在入队时完整生成
* `worker` 只负责发送，不根据 `template_id` 拼装文案

---

# 五、唯一约束总表

* `registrations.employee_id`
* `registrations.tg_id`
* `admin_list.admin_employee_id`
* `effective_leave_days(employee_id, leave_date, shift_id)`
* `effective_temporary_leaves(employee_id, leave_start_at, leave_end_at, shift_id, application_id)`
* `qc_exemption_fixed_list(shift_id, employee_id)`
* `temporary_qc_exemption_list(source_effective_temporary_leave_id)`
* `audit_results(employee_id, audit_date, audit_stage, shift_id)`
* `qc_results(employee_id, qc_date, shift_id, qc_round)`
* `approval_task_queue(application_type, application_id, approval_level, approver_employee_id)`
* `audit_task_queue(log_id, employee_id, target_date, audit_stage)`
* `qc_task_queue(log_id, employee_id)`
* `notification_queue(log_id, notify_tg_id, template_id)`

---

# 六、状态 / 结果字段对照

## 申请单

* 状态字段：`status`

## 审批任务

* 执行状态：`task_status`
* 业务结果：`approval_result`

## 审计任务

* 执行状态：`task_status`
* 业务结果：`audit_result`

## 质检任务

* 执行状态：`status`
* 业务结果：`task_result`

## 通知任务

* 执行状态：`task_status`
* 业务结果：`delivery_result`

## 事件日志

* 结果字段：`result`

## 审计结果表

* 最终结果字段：`result`

## 质检结果表

* 最终结果字段：`result`

---

# 七、开发注意事项

1. 不要在代码里擅自改字段名，以 DDL 为准
2. 不要把任务状态字段和结果字段混用
3. 不要把原始申请表当作生效表使用
4. 不要把任务队列表当作最终结果表使用
5. 新增字段或新约束后，必须同步更新本文件
6. Cursor 生成 repository / service 代码时，必须以本文件字段口径为准
7. `effective_temporary_leaves` 是 temporary leave 的真实生效事实来源
8. `temporary_qc_exemption_list` 是由真实生效事实派生出的质检辅助覆盖表，不是全天免检名单
9. `temporary_qc_exemption_list` 只用于候选集合预过滤 / 查询优化；质检模块最终是否排除员工，必须回到 `effective_temporary_leaves`，并按抽检时刻判断是否命中真实生效时间窗口；不得仅凭 `work_date` 维度整天排除
10. `notification_queue` 的数据库唯一约束以 `(log_id, notify_tg_id, template_id)` 为准；业务层可使用其他维度做补建判断，但不得将其写成新的表级唯一约束
