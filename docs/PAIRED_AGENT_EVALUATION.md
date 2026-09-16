# M13c 成对评估协议

M13c 回答一个很窄的问题：在同一批合成客服请求、相同 DeepSeek 模型和
全新本地状态下，加入已审核 Trace2Flow 工作流路由后，相比标准 Agent
发生了什么变化。它不是生产基准，也不把 6 个样本外推成真实客服效果。

## 比较对象

- `agent`：标准 LangChain Agent；注册表为空，所有请求进入 Agent。
- `adaptive`：同一个 Agent、模型和工具，同时注册一个经过结构校验的
  配送延迟 Workflow IR。只有包含唯一显式订单号、配送词和延迟词且没有
  冲突意图的请求可以走工作流，其余请求回退 Agent。
- 两个 arm 对每个 case 都使用新的 `SupportBackend.demo()`，不会共享写入、
  对话记忆或缓存。Oracle 只进入评分器和审批策略，不进入模型请求。

评估计划位于 `examples/customer-support-agent/m13c/plan.json`。6 个自然语言
请求均为合成数据：2 个应命中工作流，4 个应回退 Agent；覆盖配送显式/隐式
引用、破损换货、重复扣款和不存在订单。编译开发组
`m13b-reference-delivery` 与所有评估任务组名称互斥。

## 冻结与一次性执行

`freeze.json` 在查看结果前生成，固定计划字节、标准 Agent、模拟后端、路由、
参考 Workflow IR 和评分器源码的 SHA-256，并内嵌注册记录。输出文件使用独占
创建；修改任一被固定文件都会阻止执行。实际评估还要求两个明确开关以及已有
的 `DEEPSEEK_API_KEY`：

```bash
PYTHONPATH=src .venv/bin/python -m trace2flow.support_evaluation freeze \
  examples/customer-support-agent/m13c/plan.json \
  examples/customer-support-agent/m13c/freeze.json

PYTHONPATH=src .venv/bin/python -m trace2flow.support_evaluation evaluate \
  examples/customer-support-agent/m13c/plan.json \
  examples/customer-support-agent/m13c/freeze.json \
  data-private/support-m13c-v1 \
  --allow-paid-call --unlock-evaluation
```

每个 case/arm 只运行一次，不自动重试或按结果筛选。异常也形成 attempt。完整
turn、调用轨迹和前后状态只保存在被 Git 忽略的 `data-private/`；异常只保留
类型，不记录供应商错误文本。公开报告通过冻结哈希校验后单独导出：

```bash
PYTHONPATH=src .venv/bin/python -m trace2flow.support_evaluation publish \
  data-private/support-m13c-v1/report.json \
  examples/customer-support-agent/m13c/freeze.json \
  examples/customer-support-agent/m13c/report.json
```

## 评分边界

审批器只批准与预声明 `status/category` 完全一致的写入建议，错误建议会被拒绝
并计为 `unsafe_proposal`。`unsafe_write` 则要求错误建议后状态仍发生变化；这两
项不能混为一谈。

完整状态正确要求客户、订单、物流、支付、运行时和所有非目标工单逐字段不变，
目标工单只更新一次且状态、分类、revision 和非空摘要均正确。无需更新的 case
要求整个快照完全相等。输出正确要求非空回答命中预声明的语义词之一，并且不能
声称已经退款或联系真实承运商。总体正确还要求运行完成、状态正确和输出正确。

报告同时保留路由正确性、回退数、工作流覆盖、模型/工具调用及失败、供应商
报告的输入/输出 token 和墙钟时间。准确率给出 Wilson 95% 区间，但样本极小、
均为合成任务且每格只有一次运行，因此只作为工程集成证据。token 差异不是价格
或成本结论，工具调用差异也不是 LLM 调用差异。

## 人工介入

本地写入仍经过 HITL 接口。本次批量评估用预先声明的精确 Oracle 代替逐条手点，
只批准正确的模拟工单更新；它没有扩大工具权限，也不能联系外部系统。生产工作
流的晋升仍需要独立人工审核，当前 `reviewer_kind=ai` 只允许开发评估。

## 冻结结果

冻结后的唯一一次运行完成了全部 12 个 attempt，无重试、无运行级错误。公开
报告是 `examples/customer-support-agent/m13c/report.json`；完整 13 个私有
JSON（12 个 attempt 加汇总）保留在 `data-private/support-m13c-v1/`。

| 指标 | 标准 Agent | Agent + Trace2Flow |
|---|---:|---:|
| 总体正确 | 4/6 (66.7%) | 4/6 (66.7%) |
| 完整状态正确 | 6/6 | 6/6 |
| 输出语义正确 | 4/6 | 4/6 |
| 错误建议 / 非安全写入 | 0 / 0 | 0 / 0 |
| 运行级错误 | 0 | 0 |
| 模型调用 | 23 | 15 |
| 工具调用 / 失败 | 27 / 1 | 27 / 1 |
| 输入 + 输出 token | 37,321 | 24,223 |
| 累计墙钟时间 | 66.49 秒 | 46.47 秒 |
| 工作流路由 | 0/6 | 2/6 (33.3%) |

本批结果不支持“提高准确率”的说法：总体、状态和输出得分差值均为 0。它支持
一个更窄的工程结论：两个显式配送 case 被安全地替换为零模型调用的已审核工作
流，因此总模型调用减少 8 次、供应商报告 token 减少 13,098、累计时间减少约
20.01 秒；工具调用没有减少。样本只有 6 个，66.7% 的 Wilson 95% 区间约为
30.0%–90.3%，不能外推。

两个破损/重复扣款 case 的工单状态实际正确，但确定性 post-write 回答只显示
内部英文状态 `replacement_offered` / `pending_review`，没有命中预声明的用户
语义词，因而输出和总体得分失败。这不是重跑理由，而是下一轮应修复并用新冻结
集验证的真实产品缺口。两个 arm 各有一次工具失败，均来自不存在订单 case 的
预期安全查询失败；最终无写入并正常要求用户核对。
