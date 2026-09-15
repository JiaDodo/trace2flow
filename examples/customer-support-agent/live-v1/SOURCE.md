# DeepSeek 本地工单实验 v1

2026-09-15 完成。这里记录的工具调用由真实 DeepSeek Agent 产生，但业务输入、
客户、订单和工单状态全部是本地合成数据。不是脱敏真实客服数据，也不是生产可靠性评估。
模型编排工具；分类、建议仍由注册的确定性模拟工具计算。

采集前声明 30 个任务：编译 10、开发 8、测试 12，完整任务组与实体标识不跨分区。
保留全部 30 次运行，没有挑选成功试次，也没有重新运行某个任务来覆盖原始结果。
一次运行里的重复失败工具调用仍保留不同调用 ID。

## 来源与冻结

- 上游 AutoCompile：`b168d6760213b489e2fb2f5571f5d4e6d648dee8`；编译核心、规则和 MIT 许可证未修改。
- 基线实现：`4c3263c`；测试前的审核/报告源码检查点：`81acf50`。
- 任务计划 SHA-256：`801f17d3eb5d3cad7295de86cae0c40b9723fdaf1812e257df18da9510d46225`。
- 冻结 Workflow IR SHA-256：`5b9dc1bb54c87f34221d4a7d85fa27caf39ebc5f166f98e882dde44c0251a201`。
- 测试前评分源码 SHA-256：`fcd1bc993c13527c06f640ea51004a39eecb833248c421dbad15bf8dc697df40`。
- 模型请求/报告名称：`deepseek-v4-pro`，别名未锁定不可变模型版本；非 thinking 模式、关闭自动重试与 LangSmith 云端轨迹。
- 私有原始记录：`data-private/agent-corpus-v1/{compile,development,test}/CASE/raw.json`。
  原始记录没有提交；三份报告的 `raw_inventory` 保留全部原始文件 SHA。
- `final-freeze.json` 是测试调用前生成清单的原样归档；公开测试定义与清单是程序性隔离，
  不是权限隔离，也不能用哈希证明模型来源或独立人工审核。

`review-plan.json` 包含全部十个编译任务的 AI 审核决策与精确调用 ID。
九条完整轨迹进入编译；异属订单轨迹保留两个失败订单查询，只从编译排除，仍计入评估。
`artifacts/compile.json` 保留九条真实模型运行的本地工具事实：`recorded` 来源并且
`synthetic_environment=true`，没有模型聊天、凭据或真实客户记录。

参数映射是 AI 显式声明的未来执行合约，不是从值相等推导的模型真实血缘。
六个任务输入绑定、九个工具输出绑定、零常量、零未解决参数。
工作流五节点、三条有声明证据的依赖；客户查询和订单查询之间没有凭执行顺序添加依赖。
准入条件显式检查客户/订单存在且归属匹配，不是自动挖掘的分支。
没有人工审核；自动合约检查时间仅统计已纳入编译的记录，AI 阅读/推理投入未测量，不能冒充人工工时。

## 实际结果

编译集 10/10、开发集 8/8 的最终业务输出/安全结果与完整状态符合独立声明的预期。
这包含安全拒绝，不表示每次运行都有成功工具调用，也不评估最终客服回复文字质量。

冻结后测试集：

- Agent：12 个任务全部保留，8 个工单更新正确，4 个不执行更新且完整状态不变；
  无不安全更新尝试。48 次模型请求、45 次工具调用，其中 3 次工具调用失败。
- Workflow：接受 8/12，覆盖率 66.7%；接受的 8 个输出和完整状态均正确。
  其余 4 个安全拒绝，无错误接收。
- 相同的 8 个被接受任务：Agent 模型请求 40 次，工作流 0 次；两者工具调用都为 40 次。
  这里消除的是该固定模拟业务的在线编排调用，不证明一般业务成本收益。
- `test-11` 是零工具运行，只有原始记录；没有为符合规范化格式捏造步骤。
- 全部三十分区运行：125 次模型请求、120 次工具调用、10 次失败工具调用；
  提供方记录 155,992 输入 tokens、13,597 输出 tokens，使用量记录完整，未估算金额。

工作流使用全新的本地模拟实例执行，不回放录制响应；比对最终输出和全部客户、订单、工单状态。
计数/计时另外复执行一次新状态中的本地工作流，不额外调用模型。
Agent 收集耗时包含框架/模型/记录，工作流时间只有本地执行，不能直接宣传生产加速倍数。

## 不调用模型的复现

校验已审核编译数据：

```bash
.venv/bin/python -m trace2flow validate examples/customer-support-agent/live-v1/artifacts/compile.json
.venv/bin/python -m unittest discover -s tests -p test_agent_live_artifacts.py -v
```

三项归档回归检查来源/冻结内容、三十分区清单、独立的十二任务模拟执行与固定 Prefect 导出。
这些现在是公开的已知回归样例，不可在下一版重新当作未接触测试集。
重新挖掘可使用现有 `trace2flow mine`、`build-ir --resolution`，输出到新目录。

`artifacts/prefect_flow.py` 是固定导出器从冻结 IR 生成的目标代码，不是 Trace 携带的代码。
本轮实际在真实本地 Prefect 运行 `test-01`，五节点均 Completed；最终输出与完整状态断言通过。
下面可在仓库根目录复现同一个已知回归例，不调用模型：

```bash
PREFECT_SERVER_ALLOW_EPHEMERAL_MODE=true PREFECT_SERVER_ANALYTICS_ENABLED=false .venv/bin/python - <<'PY'
import importlib.util
from pathlib import Path
from trace2flow.agent_corpus import digest, load_plan, materialize
from trace2flow.ir import loads_workflow_ir
from trace2flow.prefect_export import export_prefect
from trace2flow.simulation import CustomerSupportSimulator

folder = Path("examples/customer-support-agent/live-v1/artifacts")
plan = load_plan(Path("examples/customer-support-agent/corpus-plan.json"))
case = next(case for case in plan.cases if case.case_id == "test-01")
payload = materialize(case)
simulator = CustomerSupportSimulator(**payload["state_before"])
registry = simulator.registry()
workflow = loads_workflow_ir((folder / "workflow.json").read_text())
assert (folder / "prefect_flow.py").read_text() == export_prefect(workflow, registry.names).source
spec = importlib.util.spec_from_file_location("known_generated_flow", folder / "prefect_flow.py")
module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(module)
result = module.run_workflow(payload["task"], registry)
state = {"customers": simulator.customers, "orders": simulator.orders, "tickets": simulator.tickets}
assert digest(result["final_output"]) == digest(payload["oracle"]["expected_final_output"])
assert digest(state) == digest(payload["oracle"]["expected_state_after"])
assert len(result["outputs"]) == 5
print("output/state match; 5 nodes executed")
PY
```

没有原始私有录制时，第三方可独立复现工作流与模拟状态验证，但不能核验历史提供方请求真实性。
更改代码、政策或工作流之后应另声明新 holdout；不能据这三十个受控任务宣称泛化成功率。
