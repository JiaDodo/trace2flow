"""Streamlit rendering for the offline M12 evidence walkthrough."""

from __future__ import annotations

import json

import streamlit as st

from .demo import candidate_dot, evidence_rows
from .live_demo import binding_rows, failure_rows, load_live_demo, run_fresh_case


def render_live_demo() -> None:
    try:
        archive = load_live_demo()
    except (OSError, ValueError, KeyError) as exc:
        st.error(f"归档校验失败，已停止展示结果：{type(exc).__name__}")
        return
    report = archive.reports["test"]
    workflow = report["workflow"]
    matched = report["matched_accepted_cases"]
    st.subheader("DeepSeek 历史录制 → 冻结工作流 → 独立模拟执行")
    st.warning(
        "真实模型编排，合成业务状态；参数绑定由 AI 显式审核，没有人工审核。"
        "分类和建议由确定性模拟工具实现，不是通用意图编译，也不是自进化。"
    )
    st.caption(
        "本页完全离线，不调用模型、不读取 API Key 或私有录制。"
        "M11 的测试任务已经公开；点击执行是已知样例回归，不是新 holdout 成绩。"
    )
    columns = st.columns(4)
    columns[0].metric(
        "工作流覆盖率（历史测试）",
        f"{workflow['accepted_cases']}/{workflow['planned_cases']}",
        help=f"{workflow['coverage']:.1%}；分母包含安全拒绝的任务。",
    )
    columns[1].metric(
        "接受任务输出 / 全状态正确",
        f"{workflow['accepted_correct_cases']}/{workflow['accepted_cases']}",
    )
    columns[2].metric("安全拒绝", str(workflow["planned_cases"] - workflow["accepted_cases"]))
    columns[3].metric(
        "相同接受任务的模型请求",
        f"{matched['agent_model_calls']} → {matched['workflow_model_calls']}",
    )
    st.write(
        f"覆盖率 {workflow['coverage']:.1%} 与接受任务正确率是两件事。"
        f"相同接受任务的工具调用仍是 {matched['agent_tool_calls']} → "
        f"{matched['workflow_tool_calls']}，没有减少工具调用。"
        "Agent 的业务结果包含正确更新与安全不变，不评估最终客服回复质量。"
    )
    raw_tab, dag_tab, execution_tab, limits_tab = st.tabs([
        "1 · 原始调用摘录", "2 · DAG 与声明绑定", "3 · 新状态验证", "4 · 失败与范围",
    ])
    with raw_tab:
        st.write("从历史任务和工具事实开始看，不需要先读几千行 JSON。")
        labels = {
            "test-01": "test-01 · 成功更新（与新状态验证对应）",
            "compile-01": "compile-01 · 纳入编译的成功轨迹",
            "compile-10": "compile-10 · 同一订单工具重复失败，未纳入编译",
            "test-11": "test-11 · 零工具运行，保留在评估分母",
        }
        selected = st.selectbox(
            "历史录制任务", list(labels), format_func=labels.get, key="live_recording",
        )
        recording = archive.recordings[selected]
        st.caption(
            "这是原始录制的任务 / 工具事实有损摘录，不是完整模型消息，也不是规范化 Trace。"
            "未补写依赖或工具步骤；聊天、系统提示和状态快照未公开。"
        )
        st.json(recording.task.model_dump(mode="json"))
        st.write(
            f"请求模型：{recording.model_requested}（未锁定不可变快照）；"
            f"模型请求 {recording.model_calls} 次，工具调用 {len(recording.calls)} 次。"
        )
        if not recording.calls:
            st.info("零工具调用：calls=[]；未伪造一个步骤来适配规范化格式。")
        for index, call in enumerate(recording.calls, 1):
            with st.expander(
                f"{index}. {call.tool} · {call.status} · {call.id}", expanded=True,
            ):
                st.json(call.model_dump(mode="json"))
        st.caption(f"原始私有文件 SHA-256：{recording.raw_sha256}；哈希不是提供方真实性证明。")
        st.download_button(
            "下载公开录制摘录（非完整原始文件）",
            recording.model_dump_json(indent=2), file_name=f"{selected}-projection.json",
            mime="application/json", key="live_projection_download",
        )
    with dag_tab:
        st.write(
            "九条已审核编译轨迹 → 五个节点、三条依赖。客户查询与订单查询之间没有数据边；"
            "不能把调用先后顺序画成依赖。节点保留每一次原始调用的 run / occurrence ID。"
        )
        st.graphviz_chart(candidate_dot(archive.candidate), width="stretch")
        with st.expander("每条依赖的逐调用证据", expanded=True):
            st.dataframe(evidence_rows(archive.candidate), width="stretch", hide_index=True)
        st.subheader("6 个任务输入绑定 / 9 个工具输出绑定 / 0 常量 / 0 未解决")
        st.caption(
            "这些是 AI 声明并用全部编译观测校验的未来执行合约，"
            "不是仅凭相同字段值推断模型真实血缘。policy_version 来自任务输入，不是常量。"
        )
        st.dataframe(binding_rows(archive.workflow), width="stretch", hide_index=True)
        for node in archive.workflow.nodes:
            with st.expander(f"{node.tool} · 具体调用、参数证据与副作用声明"):
                st.json(node.model_dump(mode="json"))
        with st.expander("冻结 Prefect 导出（本页不启动 Prefect 服务）"):
            st.code(archive.prefect_source, language="python")
            st.caption("目标代码由固定导出器生成，只能通过 ToolRegistry 调用注册工具。")
            st.download_button(
                "下载冻结 Prefect flow", archive.prefect_source,
                file_name="deepseek_frozen_flow.py", mime="text/x-python",
            )
    with execution_tab:
        st.write(
            "创建全新的 customers / orders / tickets 状态，只运行冻结工作流。"
            "预期输出和全状态来自预先独立声明的 oracle，不使用历史录制响应回放。"
        )
        cases = [case.case_id for case in archive.plan.cases if case.partition == "test"]
        selected_case = st.selectbox("已知测试样例", cases, key="live_case")
        st.caption(
            "准入是声明的客户存在、订单存在和归属一致检查，不是自动挖掘的分支。"
            "test-08～test-11 展示拒绝；每次执行重新创建状态，不覆盖历史报告。"
        )
        if st.button("运行冻结工作流（新模拟状态）", key="live_execute", type="primary"):
            st.session_state["live_result"] = run_fresh_case(archive, selected_case)
        result = st.session_state.get("live_result")
        if result is not None and result["case_id"] == selected_case:
            if result["correct"] and result["admitted"]:
                st.success("独立本地模拟验证通过：执行 5 个节点，最终输出与完整状态匹配。")
            elif result["correct"]:
                st.success(f"安全拒绝，未运行工具且完整状态不变：{result['refusal_reason']}。")
            else:
                st.error("验证失败；保留实际输出与状态，不改写预期或历史报告。")
            st.write(
                f"输出匹配：{result['output_match']}；完整状态匹配："
                f"{result['complete_state_match']}；模型请求：0；"
                "recorded_response_replay_used=false。"
            )
            actual, expected = st.columns(2)
            with actual:
                st.markdown("**实际最终输出**")
                st.json(result["actual_final_output"])
            with expected:
                st.markdown("**独立声明的预期输出**")
                st.json(result["expected_final_output"])
            st.subheader("实际状态变化")
            if result["actual_changes"]:
                st.dataframe(result["actual_changes"], width="stretch", hide_index=True)
            else:
                st.info("没有状态变化，customers / orders / tickets 全部保持不变。")
            with st.expander("完整初始状态、实际终态、预期终态与每节点输出"):
                st.json({key: result[key] for key in (
                    "state_before", "actual_state_after", "expected_state_after", "outputs",
                )})
            st.download_button(
                "下载本次离线回归结果", json.dumps(result, ensure_ascii=False, indent=2),
                file_name=f"{selected_case}-fresh-regression.json", mime="application/json",
            )
    with limits_tab:
        st.subheader("失败和零调用没有从评估中删除")
        st.dataframe(failure_rows(archive), width="stretch", hide_index=True)
        st.write(
            f"历史测试保留 {report['agent']['evaluated_cases']} 个任务，"
            f"{report['agent']['pending_cases']} 个未录制；"
            f"{report['agent_usage']['failed_tool_calls']} 次失败工具调用。"
            "compile-10 的两个订单查询分别保留调用 ID；test-11 保留零工具事实。"
        )
        by_case = {item["case_id"]: item for item in workflow["results"]}
        st.dataframe([
            {
                "任务": item["case_id"], "预期业务动作": item["expected_action"],
                "Agent 业务结果正确": item["correct"],
                "Agent 工具调用": item["tool_calls"],
                "Workflow 接受": by_case[item["case_id"]]["admitted"],
                "Workflow 输出匹配": by_case[item["case_id"]]["output_match"],
                "Workflow 全状态匹配": by_case[item["case_id"]]["complete_state_match"],
            } for item in report["agent"]["results"]
        ], width="stretch", hide_index=True)
        st.warning(
            "当前业务很窄：模拟工单、确定性分类与建议、声明的安全准入。"
            "没有真实客服数据、人工审核或自进化；未评估回复质量、金额收益或生产可靠性。"
            "修改政策 / 工作流后，需要预先另划新 holdout，不能重新宣传这些已知任务为盲测。"
        )
        with st.expander("来源、冻结标识和完整历史测试报告"):
            st.json({key: report[key] for key in (
                "scope", "plan_sha256", "workflow_sha256", "compile_sha256",
                "report_source_sha256", "review_effort", "limitations",
            )})
            st.download_button(
                "下载历史测试报告（不是本次新评估）",
                json.dumps(report, ensure_ascii=False, indent=2),
                file_name="archived-test-report.json", mime="application/json",
            )
    st.caption("上游 AutoCompile 的历史、MIT 许可与署名保留；本页证据呈现是 Trace2Flow 新增内容。")
