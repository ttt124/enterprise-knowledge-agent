# 本人复核与补充验证

以下记录为我在AI辅助提供的操作建议和样例基础上，在本机完成的补充运行与结果核对。复核所用程序和原测试代码沿用项目实现。

| 工作 | 实际结果 | 证据 |
| --- | --- | --- |
| 复现自动化测试 | 28项测试通过，末尾为OK | [本人运行日志](unittest.txt) |
| 复核三类动作路径 | 对照T01正常问答、T02制度冲突、T06工具失败的参数、结果、后续动作和原文 | [本人核对笔记](trace-review.md) |
| 修改资料副本并复测 | D001的7天改为9天，答案及引用更新，默认库仍为7天 | [实际输出](fact-change/output.json)、[Trace](fact-change/trace.json)、[资料快照](fact-change/documents.json)、[输入](fact-change/input.json) |
| 补充成员邀请场景 | 读取D006后回答普通成员应联系项目管理员，逐字引用D006#p3 | [实际输出](member-invite/output.json)、[Trace](member-invite/trace.json)、[资料快照](member-invite/documents.json)、[输入](member-invite/input.json)、[本人核对记录](member-invite/review.md) |

两项补充问答均使用真实模型 `deepseek-flash`，最终状态为 `completed`。实际输出原样保留；单列Trace和资料快照便于复核。原固定评估集仍为九例，以上两项作为本人补充检查单独记录。
