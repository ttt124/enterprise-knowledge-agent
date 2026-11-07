# 企业知识问答 Agent

本次提交对应第3题，提供一个面向合成企业制度的 Python CLI：真实模型选择检索与原文读取工具，根据工具返回决定继续查证、回答、追问或停止。回答保留文档 ID 和逐字引用，运行过程保留 Trace。资料冲突且没有优先关系时，请求确认适用制度。

交付仓库：[ttt124/enterprise-knowledge-agent](https://github.com/ttt124/enterprise-knowledge-agent)。最终提交 SHA 可用 `git rev-parse HEAD` 获取；完整源码、文档和验证记录也包含在随附 ZIP 中。

## 评审入口

- [需求与范围](docs/01-requirements.md) / [方案与取舍](docs/02-solution.md)
- [评估、发现的问题和限制](docs/03-evaluation.md)
- [AI 辅助使用说明](docs/04-ai-usage.md) / [项目复盘](docs/05-retrospective.md)
- [最终真实模型评估](examples/live/run-20261107T131207894281Z/report.md)：9/9 通过本仓库断言，使用 `deepseek-flash`。
- [本地测试记录](examples/tests/unittest-20261107T131159415747Z.txt)：28 项通过。
- [本人复核与补充验证](examples/personal-review/README.md)：本人复现28项测试、核对三类Trace，并补充完成两项真实模型检查。
- [离线流程检查](examples/mock/run-20261107T130716791849Z/report.md)：只证明流程，不证明模型效果。

评估基于六份短小合成制度。首次运行后经输出复核发现的问题和旧记录同样保留，见评估文档；固定用例通过率不代表通用问答准确率。

## 环境与安装

Python **3.11+**，实测 Windows / Python **3.13.14**。运行与测试都只用标准库，无第三方依赖，无需 `pip install`。

```powershell
python --version
python -X utf8 run.py --help
```

以下命令在获取仓库或解压附件后的项目根目录执行。使用已有虚拟环境时，可将 `python` 换成相应解释器路径。

## 离线运行：不需要密钥

```powershell
python -X utf8 run.py --mode mock --question '演示设备借用后多久归还？'
```

离线模拟器演示检索、读取与结束，最终返回 `incomplete`，退出码为 2。该模式用于流程复现，不评估业务答案。

## 真实模型运行

仅在 `.env` 不存在时复制模板，避免覆盖已经填好的配置：

```powershell
if (-not (Test-Path -LiteralPath '.env')) { Copy-Item .env.example .env }
notepad .env
```

配置项：`LLM_API_KEY`、`LLM_BASE_URL`、`LLM_MODEL`；可选 `LLM_TIMEOUT`（秒，默认60）。模板使用 DeepSeek 兼容接口和 `deepseek-flash`。配置只支持简单 `KEY=VALUE`、整行注释和成对引号，不执行插值。进程环境变量优先于 `.env`。不要提交真实密钥。

```powershell
python -X utf8 scripts/check_model.py

python -X utf8 run.py --mode live --question '演示设备借用后多久归还？' --output examples/manual/answer.json

python -X utf8 run.py --mode live --question '差旅报销期限是多少？' --output examples/manual/conflict.json
```

`check_model.py` 只检查真实 API 工具协议；正式业务效果应看批量评估记录。API 调用会消耗账户额度。接口通过 HTTPS 请求，拒绝自动重定向；错误输出不包含请求头、密钥或服务端异常原文。

上下文追问先将历史写成 JSON 数组，例如：

```json
[
  {"role": "user", "content": "我在咨询演示设备借用。"},
  {"role": "assistant", "content": "你想了解借用的哪一项规定？"}
]
```

```powershell
python -X utf8 run.py --mode live --question '那归还时怎么做？' --history history.json
python -X utf8 run.py --mode live --question '设备借用期限是多少？' --fail-tool read_document --fail-times -1
```

`--fail-times 1` 注入一次可恢复失败，`-1` 表示持续失败。`--data` 可指定资料文件；`--max-tool-calls` 默认8，`--max-model-turns` 默认12。

## 可执行测试与评估

```powershell
python -X utf8 -m unittest discover -v
python -X utf8 scripts/evaluate.py --mode mock
python -X utf8 scripts/evaluate.py --mode live
```

可用 `--case T02 --case T06` 筛选用例。每次评估新建时间戳目录，保存每例的输入、实际输出、Trace、资料快照及汇总；失败也保留。T08/T09只修改临时资料副本，不改变默认知识库。

CLI 退出码：0为 `completed`；2为明确的业务未完成、待确认或资料不足；1为配置/输入等错误。评估脚本以0表示本次全部断言通过，以1表示存在失败。业务预期为“待确认”的用例仍可通过评估。

## 实现与边界

- `src/knowledge_agent/agent.py`：模型动作循环、预算、引用校验、Trace。
- `tools.py`：关键词、同义词和中文双字片段检索；返回同主题候选，逐段读取原文。
- `model.py` / `config.py`：标准库 HTTP 与本地配置；`mock.py`：显式离线模拟。
- `data/documents.json`：自拟合成资料；`data/evaluation_cases.json`：九个评估场景。

引用检查要求来自本次成功读取的片段且逐字匹配，不能完整证明结论与证据在语义上相符。工具预算用满后允许一次不执行工具的模型收尾；若还需要工具或结果校验失败，明确返回未完成。无界面、线上发布、跨会话记忆或生产性能承诺。

投入时长约3小时。开发辅助范围、本人参与事项和验证方式见 [AI 辅助使用说明](docs/04-ai-usage.md)。
