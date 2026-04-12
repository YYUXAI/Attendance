⚠️ 本文件可能不是最新口径，请以 docs/00_system_truth.md 为唯一真相入口

# 项目蓝图（Attendance System）

## 一、整体架构分层

- handlers：只处理 Telegram 交互（输入/输出）
- services：流程编排（调用 repository + domain）
- domain：纯业务规则判断（不操作数据库）
- repositories：数据库读写（只写 SQL）
- infra：基础设施（bot / db / logger / sender）

---

## 二、核心原则

1. domain 只负责“判断对错”
2. service 只负责“流程推进”
3. handler 不写业务规则
4. repository 不写业务逻辑

---

## 三、核心流程

### 1. 注册流程
handler → register_service → repository

### 2. 打卡流程
handler → checkin_service → repository → event_logs

### 3. 审计流程
event_logs → audit_task_queue → audit_service → audit_results → notify_service

### 4. 质检流程
event_logs → qc_task_queue → qc_service → qc_results → notify_service

### 5. 审批流程
leave / temporary_leave → approval_task_queue → service → 生效表

### 6. 我的信息 / 用户信息流程
handler → profile_service → repositories（registrations / organizations / shifts / audit_results / effective_leave_days）

---

## 四、任务驱动模型

- 所有流程通过“任务队列”驱动
- tasks.py 轮询任务（pull 模型）
- 最大重试次数：3 次
- 超过后 → 通知管理员

---

## 五、统一规范

- 数据库存 UTC
- 展示使用时区转换
- 所有任务表必须同时具备：
  - 执行状态字段
  - 业务结果字段
- 字段名以 schema 为准，不强制统一命名为 `task_status` / `result`
- 两者严禁混用

## 六、模块职责

### handlers/
只做：
- 接收消息
- 参数提取
- 调用 service
- 返回结果

禁止：
- 写 SQL
- 写业务规则

---

### services/
只做：
- 调度流程
- 调用 domain
- 调用 repository
- 写事件日志

除流程编排外，可承载“同步聚合查询型服务”：
- 我的信息
- 我的统计展示
- 跨表读模型组装

---

### domain/
只做：
- 判断规则（迟到 / 早退 / 是否在岗）

---

### repositories/
只做：
- SQL 查询 / 插入 / 更新

---

### infra/
- db：数据库连接
- bot：TG 实例
- logger：日志
- sender：发送消息

---



## 七、设计理念

- 事件驱动 > 同步流程
- 数据可追溯（event_logs）
- 强约束（唯一键 + CHECK）
- 可重试（任务队列）