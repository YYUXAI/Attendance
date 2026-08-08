# Unresolved Stub / Mock / No-op / Placeholder List
## Summary
Gateway clean-break V1 新增 `gateway_provider/`、`gateway_processed_events` migration 和公开 HTTP 行为测试；该新增切片无 Stub、Mock、No-op、Placeholder、Hardcode、默认成功或吞错。

旧 Attendance Telegram ownership 中仍有以下一个已确认问题。它阻塞最终 clean-break 验收，必须在 Attendance 完整迁移切片删除。
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
- 是否阻塞需求达成：是
