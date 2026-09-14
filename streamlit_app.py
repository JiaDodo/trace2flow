"""Trace2Flow lightweight local demonstration UI."""

from __future__ import annotations

import streamlit as st

from trace2flow.demo import (
    build_demo_artifacts,
    build_recorded_retail_artifacts,
    candidate_dot,
    default_demo_texts,
    downloadable_json,
    evidence_rows,
)

st.set_page_config(page_title="Trace2Flow", page_icon="🧭", layout="wide")
st.title("Trace2Flow · Agent 轨迹到可验证工作流")
st.caption(
    "上游 AutoCompile 提供 ASP 工具级模式挖掘；Trace2Flow 新增类型边界、"
    "逐调用证据、Workflow IR、安全导出和独立模拟验证。"
)
st.info(
    "页面展示一组公开基准的脱敏记录结构；所有可执行验证仍只使用新建的"
    "合成本地状态，不连接客服系统、不发消息、不执行真实退款。"
)

recorded = build_recorded_retail_artifacts()
st.subheader("三层证据，三种不同结论")
evidence_columns = st.columns(3)
with evidence_columns[0]:
    st.markdown("**合成客服端到端**")
    st.write("用于证明完整五工具演示链路可运行；不代表真实数据表现。")
    st.code("independent_local_simulation")
with evidence_columns[1]:
    st.markdown("**公开记录结构覆盖**")
    st.write(
        f"tau 留出任务 {recorded.structural.covered_runs}/"
        f"{recorded.structural.test_runs} 覆盖四节点、三证据边。"
    )
    st.code("held_out_structure_only")
with evidence_columns[2]:
    st.markdown("**记录结构的独立执行**")
    st.write(
        f"{sum(case.status == 'passed' for case in recorded.verification.cases)}/"
        f"{len(recorded.verification.cases)} 个全新本地订单匹配最终输出和完整订单状态。"
    )
    st.code("independent_local_simulation_of_recorded_structure")

with st.expander("查看记录零售工作流的范围、绑定与验证结果"):
    st.warning(
        "记录中的商品选择由原 Agent 完成，Trace 没有足够证据编译该决策。"
        "当前可执行合同要求调用方显式提供 product_id、原 item_ids 与 new_item_ids；"
        "这不是任意换货意图解析器。"
    )
    st.caption(
        "recorded_response_replay_used=false；execution_equivalence_claimed=false。"
        "记录数据证明结构，新的合成状态只验证该结构的本地实现。"
    )
    st.graphviz_chart(candidate_dot(recorded.candidate), width="stretch")
    st.dataframe(
        [
            {
                "case_id": case.case_id,
                "status": case.status,
                "final_output_match": case.final_output_match,
                "complete_order_state_match": case.state_match,
            }
            for case in recorded.verification.cases
        ],
        width="stretch",
        hide_index=True,
    )
    st.download_button(
        "下载记录结构生成的 Prefect flow",
        recorded.prefect.source,
        file_name="recorded_retail_flow.py",
        mime="text/x-python",
    )

default_compile, default_resolution, default_holdout = default_demo_texts()
with st.sidebar:
    st.header("输入")
    compile_upload = st.file_uploader("编译 Trace JSON", type="json")
    holdout_upload = st.file_uploader("测试 Trace JSON", type="json")
    st.caption("未上传时使用仓库内明确标注为 synthetic 的客服样例。")

resolution_text = st.text_area(
    "人工确认 / ResolutionPlan JSON",
    value=default_resolution,
    height=220,
    help="可先运行查看候选，再编辑绑定、分支与副作用确认。",
)

compile_text = (
    compile_upload.getvalue().decode("utf-8")
    if compile_upload is not None
    else default_compile
)
holdout_text = (
    holdout_upload.getvalue().decode("utf-8")
    if holdout_upload is not None
    else default_holdout
)

if st.button("编译并验证", type="primary"):
    try:
        st.session_state["trace2flow_artifacts"] = build_demo_artifacts(
            compile_text,
            resolution_text,
            holdout_text,
            allow_unresolved_fallback=True,
        )
        st.session_state.pop("trace2flow_error", None)
    except Exception as exc:  # noqa: BLE001 - render safe user-facing diagnostics
        st.session_state["trace2flow_error"] = f"{type(exc).__name__}: {exc}"
        st.session_state.pop("trace2flow_artifacts", None)

if "trace2flow_error" in st.session_state:
    st.error(st.session_state["trace2flow_error"])

artifacts = st.session_state.get("trace2flow_artifacts")
if artifacts is None:
    st.write("点击“编译并验证”开始。默认样例可直接运行。")
else:
    candidate = artifacts.candidate
    workflow = artifacts.workflow
    blockers = workflow.execution_blockers()
    if artifacts.resolution_error is not None:
        st.warning(
            "当前确认方案不适用于这份 Trace；已回退为未解决 IR，"
            "请根据下方候选修改 ResolutionPlan。\n\n"
            + artifacts.resolution_error
        )
    columns = st.columns(4)
    columns[0].metric("候选节点", len(candidate.nodes))
    columns[1].metric("证据边", len(candidate.edges))
    columns[2].metric("未解决项", len(blockers))
    columns[3].metric(
        "Holdout",
        "通过" if artifacts.verification and artifacts.verification.passed else "未通过",
    )

    dag_tab, binding_tab, export_tab, verify_tab = st.tabs(
        ["DAG 与证据", "绑定与待确认项", "Prefect 导出", "独立验证"]
    )
    with dag_tab:
        st.graphviz_chart(candidate_dot(candidate), width="stretch")
        st.dataframe(evidence_rows(candidate), width="stretch", hide_index=True)
        with st.expander("上游工具级信号"):
            st.json(candidate.upstream.model_dump(mode="json"))

    with binding_tab:
        if blockers:
            st.warning("当前 IR 不可导出：\n\n- " + "\n- ".join(blockers))
        else:
            st.success("所有执行关键项均已显式解决。")
        for node in workflow.nodes:
            with st.expander(f"{node.tool} · {node.id}"):
                st.json(
                    {
                        "alignment": node.alignment_status.value,
                        "branch": node.branch_resolution.value,
                        "side_effect": node.side_effect_resolution.value,
                        "parameters": {
                            name: binding.model_dump(mode="json")
                            for name, binding in node.parameters.items()
                        },
                    }
                )

    with export_tab:
        if artifacts.prefect is None:
            st.warning(
                artifacts.export_error
                or "存在 blocker，拒绝生成可执行 Prefect 文件。"
            )
        else:
            st.success("已通过 blocker 与客服工具注册表检查。")
            st.code(artifacts.prefect.source, language="python", line_numbers=True)
            st.download_button(
                "下载 generated_flow.py",
                artifacts.prefect.source,
                file_name="generated_flow.py",
                mime="text/x-python",
            )

    with verify_tab:
        report = artifacts.verification
        if report is None:
            st.warning(
                artifacts.verification_error
                or "工作流尚不可执行，或未提供测试集。"
            )
        else:
            if report.passed:
                st.success("独立本地模拟验证通过。")
            else:
                st.error("至少一个测试运行未匹配。")
            st.caption(
                "validation_scope=independent_local_simulation；结果仅证明合成受控场景。"
            )
            st.dataframe(
                [
                    {
                        "run_id": case.run_id,
                        "status": case.status,
                        "final_output_match": case.final_output_match,
                        "state_match": case.state_match,
                        "state_changes": len(case.actual_changes),
                    }
                    for case in report.cases
                ],
                width="stretch",
                hide_index=True,
            )
            st.json(report.model_dump(mode="json"))

    st.divider()
    st.subheader("下载审计产物")
    for filename, content in downloadable_json(artifacts).items():
        st.download_button(
            f"下载 {filename}",
            content,
            file_name=filename,
            mime="application/json",
            key=f"download-{filename}",
        )

st.divider()
st.caption(
    "许可证与署名：保留 mirkokiefer/autocompile 的 MIT 历史与许可证；"
    "界面和验证链路为 Trace2Flow 新增贡献。"
)
