# Unresolved Stub / Mock / No-op / Placeholder List
## Summary
融合服务重载与验收复跑后，仍有两个旧 Attendance 业务问题被本轮 C 类范围明确禁止修复；它们不是双 Bot 融合引入的问题，不阻塞统一路由边界。
## Items
### 1. 已下线 leave/tleave/QC 旧 callback 保持 no-op
- 类型：No-op
- 对应 Review 问题：既有 callback handler 仅 answer 并记录日志
- 位置线索：`handlers/menu.py`
- 无法修复原因：功能在融合前已下线；本轮明确禁止恢复离岗、临时离岗、审批和 QC 旧业务。
- 缺失条件：这些业务的当前产品规则、状态机和恢复授权。
- 当前影响：统一壳不再声明或转发这些旧 callback；它们只保留在旧 Attendance 自身代码中。
- 风险等级：Low
- 建议后续处理：独立业务目标中决定删除旧按钮协议，或按新规则恢复完整 handler。
- 是否阻塞需求达成：否

### 2. 非允许考勤群仍可能返回旧的成功文案
- 类型：默认成功
- 对应 Review 问题：旧 check-in chat roster deny 分支不落库但回复成功
- 位置线索：`handlers/checkin.py`
- 无法修复原因：这是融合前 Attendance 业务语义；本轮明确禁止修复与双 Bot 无直接因果关系的旧业务 bug。
- 缺失条件：产品对非允许群的最终提示和兼容策略。
- 当前影响：不影响双 Bot 来源幂等，但可能让旧 Attendance 场景产生误导提示。
- 风险等级：Medium
- 建议后续处理：另立 Attendance 业务目标，确定失败提示及审计策略后修复。
- 是否阻塞需求达成：否
