# Cursor 实现规则（强约束）

本文件用于约束 Cursor 在实现代码时的行为。

所有生成代码必须遵守本文件规则，否则视为错误实现。

---

# 一、优先级规则

实现优先级必须遵守：

1. docs00_system_truth.md
2. docs02_database_schema.md
3. 本文件（docs04_cursor_rules.md）
4. 代码实现

若出现冲突：

👉 以上级文档为准，不得自行脑补

---

# 二、基础原则

## 1. Schema 优先

* 所有表结构必须严格遵守 docs02_database_schema.md
* 不允许：

  * 自行新增字段
  * 自行修改字段名
  * 自行修改字段类型
  * 自行增加/删除约束

若发现 schema 不满足需求：

👉 必须先更新 docs02，再实现代码

---

## 2. System Truth 优先

* 所有业务规则必须遵守 docs00_system_truth.md
* 禁止在代码中发明新的业务规则

---

## 3. 分层原则

必须遵守：

* handlers：只做交互，不写业务逻辑
* services：只做业务编排
* repositories：只做 SQL

禁止：

* handler 写 SQL
* service 拼 SQL
* repository 写业务判断

---

## 4. 任务系统原则

所有任务表都必须区分：

* 执行状态字段
* 业务结果字段

禁止混用。

注意：

* 字段命名以 schema 为准
* 不强制统一为 `task_status` / `result`

---

# 三、通知模块规则

## 1. notification_queue 的边界

notification_queue 只负责：

👉 异步通知任务

不包括：

* handler 内即时 reply
* callback.answer
* 输入校验报错
* 菜单提示
* 群内即时回执

---

## 2. 发送规则

* worker 只负责发送
* worker 不参与业务逻辑
* worker 不根据 template_id 生成文案
* reply_content 必须在入队时完整生成

---

## 3. template_id 规则

必须遵守 docs05_notification_templates.md：

* 不允许写 `template_id = NULL`
* 不允许硬编码未注册 template_id
* 不允许复用旧编号表达新语义
* 不允许使用 template_id 拼装文案

---

## 4. 通知补建 vs 发送重试

必须区分：

### 通知任务缺失补建

* 属于业务生成层职责
* 前提是：该通知任务本应存在但未成功入队

### 通知发送失败重试

* 属于 notification worker 职责
* 前提是：任务已成功入队

禁止：

* 用“重新插一条新通知”替代发送重试
* 混淆补建与重试

---

# 四、离岗与质检强约束

## 1. 唯一真相源

关于离岗免检：

👉 唯一真相表 = `effective_temporary_leaves`

禁止：

* 仅使用 `temporary_qc_exemption_list` 判定免检
* 绕过 effective 表

---

## 2. 判定规则（必须实现）

质检是否排除员工，必须使用：

`qc_time ∈ [leave_start_at, leave_end_at)`

必须实现：

* `leave_start_at <= qc_time < leave_end_at`

禁止：

* 使用 work_date 判断全天免检
* 使用“存在记录”判断免检
* 把离岗理解为“全天免检”

---

## 3. temporary_qc_exemption_list 使用规则

该表仅用于：

👉 质检候选集合预过滤 / 查询优化

最终判定必须回到：

👉 `effective_temporary_leaves`

禁止：

* 直接把该表当最终免检依据
* 只查该表就决定排除

---

## 4. 写入规则

写入 `temporary_qc_exemption_list` 必须满足：

* 来源：`effective_temporary_leaves`
* 时机：进入 EFFECTIVE 时
* 一条 effective 记录对应一条 exemption 记录
* 必须幂等

禁止：

* 从 `temporary_leave_applications` 直接写入
* 在 APPROVED 阶段写入
* 重复插入导致事务失败

---

## 5. 质检未送达超时收口（强约束）

背景：

质检任务一旦进入 `qc_task_queue`，就必须在固定时限后收口，避免任务悬挂导致单轮完结公告与班次汇总公告无法触发。

必须遵守（15 分钟硬期限，口径以 `docs00_system_truth.md` / `docs02_database_schema.md` / `docs03_state_machine.md` 为准）：

收口定义：
必须进入终态集合（如 COMPLETED / TIMEOUT / CANCELLED 等），不得停留在中间状态。

1. 所有进入 `qc_task_queue` 的任务，**15 分钟内必须收口**，不得长期停留在非终态。
2. 已送达任务：
   - 计时起点 = `first_private_notify_sent_at`
   - 截止时间 = `first_private_notify_sent_at` + 15 分钟
3. 未送达任务：
   - 条件：`status = PENDING` 且 `first_private_notify_sent_at IS NULL`
   - 兜底计时起点 = `created_at`
   - 截止时间 = `created_at` + 15 分钟
4. 未送达 = 未完成：
   - 单轮完结公告与班次汇总公告不得忽略“未送达且无 qc_results”的员工，必须归入未完成口径。

禁止：

* 将 timeout 收口逻辑再次收窄为“只处理已送达任务（仅依赖 `first_private_notify_sent_at`）”
* 允许任务长期停留在 `PENDING` 并阻塞单轮完结（以 “未送达 / 未触发超时 / 无结果” 为理由悬挂）

# 五、审计模块规则

## 1. 当前有效阶段

当前业务只允许：

* CHECKIN
* CHECKOUT

说明：

* schema 可能仍保留 BREAK
* 当前实现不得启用 BREAK 逻辑

---

## 2. 审计结果优先级

必须遵守 docs00：

* ON_LEAVE
* TEMPORARY_LEAVE
* EXEMPT
* 再进入正常打卡判定

---

# 六、审批模块规则

## 1. 审批结果与通知解耦

必须：

* 审批结果写库优先
* 通知失败不影响审批结果

禁止：

* 因通知失败回滚审批结果

---

## 2. 审批任务状态说明

当前审批任务状态采用一期历史兼容口径：

* APPROVED_DONE
* REJECTED_DONE

实现时必须遵守：

* 审批业务结论以 `approval_result` 为准
* 不得仅凭 `task_status` 判断最终审批结论

---

# 七、同步查询类功能（Read Model）

以下场景属于同步查询类功能：

* 我的信息
* 我的统计
* 我的假期记录
* 我的质检记录

特点：

* 不进入任务队列
* 不产生 event_logs
* 不写结果表
* 由 handler 触发，service 聚合，repository 查询

禁止：

* 为展示需求改写结果表
* 把同步查询误建成任务流

---

# 八、严禁行为总结

禁止：

* 修改 schema 却不同步 docs02
* 发明新业务规则
* 把派生表当真相源
* 用 existence 判断代替时间窗口
* 用“当天有记录”代替“当前是否生效”
* 依赖 DB 报错作为业务逻辑
* 绕过 notification_queue 发送异步通知
* 混用状态字段与结果字段

---

# 九、最终原则

Cursor 生成的任何代码，都必须体现：

1. 状态 ≠ 结果
2. 任务 ≠ 结果
3. 系统错误不污染业务状态
4. 离岗免检 = 时间窗口行为，不是按天行为
5. notification_queue 只负责异步通知任务
