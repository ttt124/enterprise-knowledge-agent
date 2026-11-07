# Knowledge Agent 评估（live）

模型：`deepseek-flash`

通过 9/9。

复核注记：以上为当时旧断言的原始结果。按加强后的断言重新检查，T02、T06未通过，详见 [posthoc-review.json](posthoc-review.json)。修正后的完整评估见[最终报告](../run-20261107T131207894281Z/report.md)。原始输出与汇总保持不变。

本报告检查状态、必需引用、逐字来源、已读证据与调用预算。离线结果仅验证流程，不能代替真实模型评估。
每例保留 input.json、output.json、trace.json 和 documents.json；失败记录同样保留。

| 用例 | 名称 | 结果 | 实际状态 |
| --- | --- | --- | --- |
| T01 | 设备借用期限 | 通过 | completed |
| T02 | 差旅报销期限冲突 | 通过 | needs_clarification |
| T03 | 资料外问题 | 通过 | insufficient_evidence |
| T04 | 设备同义口语检索 | 通过 | completed |
| T05 | 历史指代归还流程 | 通过 | completed |
| T06 | 读取工具持续失败 | 通过 | incomplete |
| T07 | 仅一次工具调用预算 | 通过 | incomplete |
| T08 | 临时资料改为十天 | 通过 | completed |
| T09 | 新增设备期限冲突 | 通过 | needs_clarification |
