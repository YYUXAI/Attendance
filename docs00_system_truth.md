# docs00_system_truth.md

本文件定义考勤系统的“唯一业务真相（System Truth）”。

所有模块（审计 / 通知 / 审批 / 质检 / 报表）必须严格遵守本文件定义的业务口径。
若实现与本文件冲突，以本文件为准。

---

# 一、核心原则

## 1. 状态 ≠ 结果
- 审计过程中的中间状态（PENDING / PROCESSING）不是最终结果
- 只有终态（NORMAL / LATE / ABSENT 等）才是结果

## 2. 任务 ≠ 结果
- audit_task_queue 表示“执行过程”
- audit_results 表示“最终结果”
- notification_queue 表示“通知任务”

## 3. 系统错误不污染业务状态
- 系统异常（发送失败 / SQL异常）不得写入业务结果字段
- 系统错误只记录在日志或 error_message 中

---

# 二、时间与时区规则

## 1. 所有时间存储为 UTC
## 2. 所有业务判断使用班次时区

---

# 三、班次与工作日（work_date）

## 1. 非跨夜班（is_overnight = false）

工作日定义：

👉 work_date = 当前班次时区下的本地自然日

说明：
- 不得因为当前时间 < 上班时间，就回拨到前一天
- 即使当前时间早于 checkin_time，仍属于今天

---

## 2. 跨夜班（is_overnight = true）

规则：

- 若 当前时间 < checkin_time → 属于前一天
- 否则 → 属于当天

---

# 四、审计阶段定义

当前业务实际使用：

- CHECKIN（上班）
- CHECKOUT（下班）

说明：

- 数据库 schema 当前仍可能保留 BREAK 枚举，属于兼容保留
- 当前业务规则、状态机与代码实现中，不使用 BREAK
- 未经文档更新，不得自行启用 BREAK 相关逻辑

---

# 五、审计结果优先级

按优先级从高到低：

1. ON_LEAVE（休假）
2. TEMPORARY_LEAVE（离岗）
3. EXEMPT（免检/免打卡，当前预留）
4. 正常打卡判断：
   - CHECKIN：NORMAL / LATE / ABSENT
   - CHECKOUT：NORMAL / EARLY_LEAVE / ABSENT

---

# 六、日级缺勤规则（重要）

若某员工在某工作日同时满足：

1. 未命中休假（effective_leave_days）
2. 未命中离岗覆盖
3. CHECKIN = ABSENT
4. CHECKOUT = ABSENT

则判定：

👉 DAILY_ABSENT（全天缺勤）

说明：

- 这是“日级汇总结果”，不是 audit_results.result
- 不写入 audit_results 表
- 仅用于：
  - 报表统计
  - 通知汇总

---

# 七、通知模块原则

## 1. notification_queue 是异步通知任务的唯一发送入口

说明：

- 仅适用于进入 `notification_queue` 的异步通知任务
- 不适用于 handler 内即时 reply / callback.answer
- 不适用于表单输入错误提示、菜单提示、群内即时回执

---

## 2. reply_content 为最终内容

- 入队前必须生成完整内容
- worker 只负责发送
- worker 不参与业务判断
- worker 不根据 template_id 生成文案

---

## 3. 所有异步通知统一使用 HTML 发送

规则：

- parse_mode = HTML
- disable_web_page_preview = True

# 八、审计通知规则（3003 / 3004 / 3005 / 3006）

---

## 3003 开班群公告

- 上班时间触发
- 允许补建

---

## 3004 组长私信

- 上班时间触发
- 允许补建
- 按模板生成（docs05）

---

## 3005 部门负责人汇总（一期规则）

### 聚合规则（临时口径）

1. organizations 表中：
   👉 相同 highest_responsible_employee_id → 视为同一部门

2. 每一条 organization 记录：
   👉 视为一个“组”

3. leader_employee_id：
   👉 视为该组负责人

---

### 组名规则（当前阶段）

无 group_name 字段时：

👉 使用：{leader_english_name}组

---

### 注意

- department_name 仅用于展示
- 不作为聚合键
- 当前为一期临时规则，后续可替换为组织树

---

## 3006 下班群提醒

### 触发规则

仅允许在以下窗口创建：

👉 checkout_time ~ checkout_time + 5分钟

---

### 禁止

- 禁止补发历史下班提醒
- 禁止跨天补发
- 禁止在上班时间发出

---

# 九、防重规则（重要）

## 1. 数据库唯一约束

notification_queue 的数据库唯一约束以 schema 为准：

- `(log_id, notify_tg_id, template_id)`

这表示：

👉 同一日志事件 + 同一接收人 + 同一通知类型，只允许一条通知任务

---

## 2. 业务补建判定维度

对于部分通知语义（如班次开班公告、下班提醒、负责人汇总），
业务层可以使用以下维度辅助判断“当天该不该补建”：

- shift_id
- work_date
- notify_tg_id
- template_id

注意：

👉 这只是业务补建判定维度，不等于数据库唯一约束
👉 不得将其写成新的表级唯一约束口径

# 十点补充：审批任务状态例外口径

当前审批任务表中，`task_status` 仍沿用以下历史兼容状态：

- APPROVED_DONE
- REJECTED_DONE

这属于一期实现口径，暂不强行改写 schema。

必须遵守：

- 审批业务结论以 `approval_result` 为准
- 不得仅凭 `task_status` 推导最终审批结论
- 后续若重构审批任务状态机，应单独更新 docs02 / docs03 / DDL

# 十一、一期结构说明（重要）

当前系统允许以下“临时规则”：

- 部门 = highest_responsible_employee_id
- 组 = organization 行

这些规则属于：

👉 **一期过渡方案**

后续可升级为：

- 组织树结构
- group_name 字段

# 十二、同步查询类功能（Read Model）（新增）

定义：

👉 由用户主动触发，实时查询并聚合多个表的数据，并直接返回展示结果

特点：

- 不进入任务队列
- 不产生 event_logs
- 不属于审计 / 审批 / 质检流程
- 不写入结果表
- 不涉及状态机

典型场景：

- 我的信息
- 我的考勤统计
- 我的假期记录
- 我的质检记录

实现约束：

1. handler 只负责触发与返回
2. service 负责聚合多个数据源
3. repository 负责基础查询
4. 不允许为了展示需求修改结果表结构

## 十三、质检临时免检规则（强约束）

本系统中，离岗报备对质检的影响，必须遵守以下统一规则：

### 1. 唯一真相来源

离岗免检的唯一事实来源为：

effective_temporary_leaves

任何模块不得绕过该表直接判定免检。

---

### 2. 判定规则（核心）

质检是否排除员工，必须基于“时间窗口”判断：

qc_draw_time ∈ [leave_start_at, leave_end_at)

仅当质检抽取时刻落在离岗生效时间段内，员工才视为临时免检。

---

### 3. 禁止行为（必须遵守）

禁止以下错误逻辑：

- ❌ 仅根据 work_date 判断免检
- ❌ 仅根据 temporary_qc_exemption_list 是否存在记录判断免检
- ❌ 将“当天存在离岗记录”解释为“全天免检”
- ❌ 将派生表当作最终真相源

---

### 4. 派生表的角色定义

temporary_qc_exemption_list 的定位是：

→ 由 effective_temporary_leaves 派生出的“质检免检覆盖记录表”

其作用：

- 用于优化查询（快速筛选候选人）
- 用于减少质检抽人时的扫描范围

但：

→ 不具备最终判定权

最终判定必须回到 effective_temporary_leaves。

---

### 5. 写入规则

temporary_qc_exemption_list 的写入必须满足：

- 来源：effective_temporary_leaves
- 时机：离岗进入 EFFECTIVE 时
- 一条 effective 记录对应一条派生记录

---

### 6. 系统设计原则

离岗免检必须满足以下统一原则：

离岗免检 = 时间段行为，不是按天行为

系统必须保证：

- 离岗期间 → 免检
- 离岗结束 → 自动恢复参与质检（无需删除派生记录）

---

### 7. 设计优先级

在以下两者冲突时：

1. 查询性能
2. 判定准确性

必须优先保证：

判定准确性（时间窗口）

---