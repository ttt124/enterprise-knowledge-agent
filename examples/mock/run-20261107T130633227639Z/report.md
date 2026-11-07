# Knowledge Agent 评估（mock）

模型：`offline-flow-simulator`

离线流程断言通过 9/9。

本报告检查离线结束状态、无伪造引用、实际工具调用与预算、终止事件和注入故障记录，不评估业务答案。
本次为 offline_flow：业务期望全部标记 not_evaluated；模拟器应返回 incomplete 且不伪造引用。通过比例不代表模型效果。
每例保留 input.json、output.json、trace.json 和 documents.json；失败记录同样保留。

| 用例 | 名称 | 结果 | 实际状态 |
| --- | --- | --- | --- |
| T01 | 设备借用期限 | 通过 | incomplete |
| T02 | 差旅报销期限冲突 | 通过 | incomplete |
| T03 | 资料外问题 | 通过 | incomplete |
| T04 | 设备同义口语检索 | 通过 | incomplete |
| T05 | 历史指代归还流程 | 通过 | incomplete |
| T06 | 读取工具持续失败 | 通过 | incomplete |
| T07 | 仅一次工具调用预算 | 通过 | incomplete |
| T08 | 临时资料改为十天 | 通过 | incomplete |
| T09 | 新增设备期限冲突 | 通过 | incomplete |
