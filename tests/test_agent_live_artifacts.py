"""Archive integrity/regression, not a new untouched-model test estimate."""

import ast
import hashlib
import json
import unittest
from pathlib import Path

from trace2flow.agent_contract_review import ContractReviewPlan
from trace2flow.agent_corpus import digest, load_plan, materialize
from trace2flow.agent_evaluation import evaluate_workflow
from trace2flow.candidate import CandidateDag
from trace2flow.io import canonical_json, load_trace_dataset
from trace2flow.ir import loads_workflow_ir
from trace2flow.prefect_export import export_prefect

ROOT = Path(__file__).resolve().parents[1]
ARCHIVE = ROOT / "examples/customer-support-agent/live-v1"


class LiveArchiveTests(unittest.TestCase):
    def setUp(self):
        self.plan = load_plan(ROOT / "examples/customer-support-agent/corpus-plan.json")
        self.data = load_trace_dataset(ARCHIVE / "artifacts/compile.json")
        self.workflow = loads_workflow_ir(
            (ARCHIVE / "artifacts/workflow.json").read_text()
        )
        self.freeze = json.loads((ARCHIVE / "final-freeze.json").read_text())

    def test_compile_population_provenance_and_frozen_content_identity(self):
        decisions = ContractReviewPlan.model_validate(
            json.loads((ARCHIVE / "review-plan.json").read_text())
        )
        self.assertEqual(len(self.data.runs), 9)
        self.assertEqual(self.freeze["reviewed_excluded_cases"], ["compile-10"])
        self.assertEqual(
            self.freeze["workflow_sha256"],
            digest(self.workflow.model_dump(mode="json")),
        )
        self.assertEqual(
            self.freeze["compile_sha256"], digest(self.data.model_dump(mode="json"))
        )
        self.assertEqual(
            self.freeze["review_plan_sha256"], digest(decisions.model_dump(mode="json"))
        )
        source_sha = hashlib.sha256(canonical_json(self.data).encode()).hexdigest()
        self.assertEqual(self.workflow.source_sha256, source_sha)
        candidate = CandidateDag.model_validate_json(
            (ARCHIVE / "artifacts/candidate.json").read_text()
        )
        self.assertEqual(candidate.source_sha256, source_sha)
        self.assertEqual(self.workflow.execution_blockers(), [])
        self.assertEqual(len(self.workflow.nodes), 5)
        self.assertEqual(len(self.workflow.edges), 3)
        self.assertFalse(
            any(
                binding.kind in {"constant", "unresolved"}
                for node in self.workflow.nodes
                for binding in node.parameters.values()
            )
        )
        specs = {case.case_id: case for case in self.plan.cases}
        for run in self.data.runs:
            case = specs[run.inputs["task_id"]]
            self.assertEqual(case.partition, "compile")
            self.assertEqual(run.provenance.kind, "recorded")
            self.assertIs(run.metadata["synthetic_environment"], True)
            self.assertEqual(
                run.metadata["raw_sha256"], decisions.cases[case.case_id].raw_sha256
            )
            self.assertEqual(digest(run.inputs), digest(materialize(case)["task"]))
            self.assertEqual(
                digest(run.state_before), digest(materialize(case)["state_before"])
            )

    def test_archived_report_inventory_and_independent_execution_agree(self):
        raw_hashes = []
        for role in ("compile", "development", "test"):
            report = json.loads((ARCHIVE / (role + "-report.json")).read_text())
            expected = {
                case.case_id for case in self.plan.cases if case.partition == role
            }
            self.assertEqual(
                {item["case_id"] for item in report["raw_inventory"]}, expected
            )
            self.assertEqual(len(report["raw_inventory"]), len(expected))
            self.assertEqual(report["agent"]["pending_cases"], 0)
            self.assertIs(report["agent"]["score_final"], True)
            raw_hashes.extend(item["raw_sha256"] for item in report["raw_inventory"])
        self.assertEqual(len(raw_hashes), 30)
        self.assertEqual(len(set(raw_hashes)), 30)
        test = json.loads((ARCHIVE / "test-report.json").read_text())
        self.assertEqual(
            test["report_source_sha256"], self.freeze["report_source_sha256"]
        )
        self.assertEqual(test["workflow_sha256"], self.freeze["workflow_sha256"])
        self.assertEqual(test["agent_usage"]["model_calls"], 48)
        self.assertEqual(test["agent_usage"]["failed_tool_calls"], 3)
        zero = next(
            item
            for item in test["agent_usage"]["results"]
            if item["case_id"] == "test-11"
        )
        self.assertEqual(zero["tool_calls"], 0)
        fresh = evaluate_workflow(self.plan, self.workflow, "test", self.data)
        self.assertEqual(fresh, test["workflow"])
        self.assertEqual(fresh["accepted_cases"], 8)
        self.assertEqual(fresh["accepted_correct_cases"], 8)
        self.assertEqual(fresh["unsafe_acceptances"], 0)

    def test_prefect_archive_is_exact_allowlisted_export_not_trace_code(self):
        tools = {node.tool for node in self.workflow.nodes}
        artifact = export_prefect(self.workflow, tools)
        source = (ARCHIVE / "artifacts/prefect_flow.py").read_text()
        self.assertEqual(source, artifact.source)
        tree = ast.parse(source)
        imports = {
            node.module for node in ast.walk(tree) if isinstance(node, ast.ImportFrom)
        }
        self.assertEqual(imports, {"__future__", "prefect", "trace2flow.runtime"})
        calls = {
            node.func.id
            for node in ast.walk(tree)
            if isinstance(node, ast.Call) and isinstance(node.func, ast.Name)
        }
        self.assertTrue({"eval", "exec", "compile", "__import__"}.isdisjoint(calls))


if __name__ == "__main__":
    unittest.main()
