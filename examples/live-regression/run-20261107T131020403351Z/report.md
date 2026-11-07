# Knowledge Agent 评估（live）

模型：`deepseek-flash`

业务与证据断言通过 4/4。

本报告检查状态、必需引用、逐字来源、已读证据与调用预算。
本次对真实输出检查各用例业务期望与证据；仍需人工复核语义与适用范围。
每例保留 input.json、output.json、trace.json 和 documents.json；失败记录同样保留。

| 用例 | 名称 | 结果 | 实际状态 |
| --- | --- | --- | --- |
| T02 | 差旅报销期限冲突 | 通过 | needs_clarification |
| T06 | 读取工具持续失败 | 通过 | incomplete |
| T07 | 仅一次工具调用预算 | 通过 | incomplete |
| T09 | 新增设备期限冲突 | 通过 | needs_clarification |
