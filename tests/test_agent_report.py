"""Declared occurrence contracts and reports; never make paid calls."""

import hashlib
import json
import tempfile
import unittest
from contextlib import redirect_stderr, redirect_stdout
from io import StringIO
from pathlib import Path
from unittest.mock import patch

from test_agent_corpus import PLAN_PATH, complete_case
from test_agent_corpus import declaration as fixture_review

from trace2flow.agent_contract_review import Decision, declaration
from trace2flow.agent_contract_review import main as contract_main
from trace2flow.agent_corpus import freeze, load_plan, make_collector
from trace2flow.agent_report import build_report, freeze_main, usage_metrics
from trace2flow.agent_report import main as report_main
from trace2flow.agent_review import (
    build_main,
    combine_reviewed,
    declared_resolution,
    review_recording,
)
from trace2flow.candidate import mine_candidate_dag
from trace2flow.ir import build_workflow_ir


class AgentReportTests(unittest.TestCase):
    def setUp(self):
        self.plan = load_plan(PLAN_PATH)
        self.instance = complete_case(self.plan, self.plan.cases[0])
        self.raw = json.dumps(self.instance.raw()).encode()
        self.decision = Decision(
            raw_sha256=hashlib.sha256(self.raw).hexdigest(),
            decision="include",
            rationale="explicit offline fixture contract, no human review",
            roles={call["tool"]: call["id"] for call in self.instance.calls},
        )

    def workflow(self):
        datasets = []
        for case in self.plan.cases[:3]:
            raw, review = fixture_review(self.plan, complete_case(self.plan, case))
            datasets.append(review_recording(self.plan, raw, review))
        data = combine_reviewed(datasets, "offline-report-compile")
        candidate = mine_candidate_dag(data)
        return data, build_workflow_ir(
            data, candidate, declared_resolution(data, candidate)
        )

    def test_contract_declares_paths_instead_of_constants_or_read_order(self):
        review = declaration(self.plan, self.raw, self.decision, "AI fixture")
        data = review_recording(self.plan, self.raw, review)
        calls = {step.tool: step for step in data.runs[0].steps}
        self.assertEqual(calls["lookup_order"].depends_on, [])
        policy = calls["recommend_action"].metadata["binding_declarations"][
            "policy_version"
        ]
        self.assertEqual(policy["kind"], "task_input")
        self.assertEqual(policy["path"], ["policy_version"])
        self.assertIs(calls["classify_issue"].params["damaged"], False)

    def test_wrong_occurrence_hash_or_role_is_rejected(self):
        wrong = self.decision.model_copy(deep=True)
        wrong.raw_sha256 = "0" * 64
        with self.assertRaisesRegex(ValueError, "raw SHA"):
            declaration(self.plan, self.raw, wrong, "AI fixture")
        wrong = self.decision.model_copy(deep=True)
        wrong.roles["lookup_customer"], wrong.roles["lookup_order"] = (
            wrong.roles["lookup_order"],
            wrong.roles["lookup_customer"],
        )
        with self.assertRaisesRegex(ValueError, "contradicts"):
            declaration(self.plan, self.raw, wrong, "AI fixture")

    def test_repeated_occurrences_are_not_merged_to_fit_contract(self):
        raw = self.instance.raw()
        repeated = json.loads(json.dumps(raw["calls"][0]))
        repeated["id"] = "another-distinct-customer"
        raw["calls"].append(repeated)
        content = json.dumps(raw).encode()
        decision = self.decision.model_copy(deep=True)
        decision.raw_sha256 = hashlib.sha256(content).hexdigest()
        with self.assertRaisesRegex(ValueError, "five explicitly"):
            declaration(self.plan, content, decision, "AI fixture")
        decision.decision, decision.roles = "exclude_from_compilation", {}
        review = declaration(self.plan, content, decision, "AI fixture")
        self.assertEqual(len(review.calls), 6)
        self.assertIsNone(review_recording(self.plan, content, review))

    def test_usage_failure_and_pending_runs_are_not_hidden(self):
        collector = make_collector(
            self.plan, self.plan.cases[15], model_id="fake", scripted=True
        )
        collector.model_calls, collector.ending = 2, "execution_error:TimeoutError"
        metrics = usage_metrics(collector.raw())
        self.assertFalse(metrics["usage_complete"])
        report = build_report(self.plan, [collector.raw()], "development")
        self.assertEqual(report["agent"]["planned_cases"], 8)
        self.assertEqual(report["agent"]["correct_cases"], 0)
        self.assertFalse(report["agent"]["score_final"])
        self.assertEqual(report["agent_usage"]["model_calls"], 2)

    def test_workflow_metrics_have_independent_state_and_call_counts(self):
        data, workflow = self.workflow()
        records = [
            complete_case(self.plan, case).raw() for case in self.plan.cases[10:14]
        ]
        report = build_report(self.plan, records, "development", workflow, data)
        self.assertEqual(report["workflow"]["coverage"], 0.5)
        self.assertEqual(report["matched_accepted_cases"]["cases"], 4)
        self.assertEqual(report["matched_accepted_cases"]["workflow_tool_calls"], 20)
        self.assertEqual(report["matched_accepted_cases"]["workflow_model_calls"], 0)
        self.assertTrue(
            all(
                item["independent_measurement_correct"]
                for item in report["matched_accepted_cases"]["results"]
            )
        )
        self.assertIsNone(report["review_effort"]["human_review_minutes"])

    def test_test_cli_requires_pre_frozen_generator_before_reading_results(self):
        with tempfile.TemporaryDirectory() as temp:
            directory = Path(temp)
            freeze(self.plan, directory / "freeze")
            args = [
                str(PLAN_PATH),
                str(directory / "not-collected"),
                "--partition",
                "test",
                "--manifest",
                str(directory / "freeze/manifest.json"),
                "--output",
                str(directory / "report.json"),
            ]
            for extra in ([], ["--unlock-test"]):
                with (
                    redirect_stderr(StringIO()),
                    patch("trace2flow.agent_report.build_report") as builder,
                    self.assertRaises(SystemExit),
                ):
                    report_main(args + extra)
                builder.assert_not_called()

    def test_final_freeze_rejects_unconfirmed_or_cherry_picked_compile_population(self):
        from trace2flow.agent_corpus import digest

        data, workflow = self.workflow()
        with tempfile.TemporaryDirectory() as temp:
            directory = Path(temp)
            (directory / "compile.json").write_text(data.model_dump_json())
            (directory / "workflow.json").write_text(workflow.model_dump_json())
            decisions = {
                "schema_version": "agent-contract-review-plan/1.0",
                "plan_sha256": digest(self.plan.model_dump(mode="json")),
                "reviewer": "AI fixture",
                "reviewer_kind": "ai",
                "redaction_confirmed": True,
                "cases": {
                    case.case_id: {
                        "raw_sha256": "0" * 64,
                        "decision": "include",
                        "rationale": "fixture",
                        "roles": {},
                    }
                    for case in self.plan.cases[:10]
                },
            }
            (directory / "decisions.json").write_text(json.dumps(decisions))
            args = [
                str(PLAN_PATH),
                "--workflow",
                str(directory / "workflow.json"),
                "--compile",
                str(directory / "compile.json"),
                "--review-plan",
                str(directory / "decisions.json"),
                "--output-dir",
                str(directory / "final"),
            ]
            for extra in ([], ["--confirm-unseen-test"]):
                with redirect_stderr(StringIO()), self.assertRaises(SystemExit):
                    freeze_main(args + extra)
            self.assertFalse((directory / "final").exists())

    def test_compile_contract_intake_requires_complete_inventory(self):
        from trace2flow.agent_corpus import digest

        with tempfile.TemporaryDirectory() as temp:
            directory = Path(temp)
            recordings = directory / "recordings"
            recordings.mkdir()
            decisions = {
                "schema_version": "agent-contract-review-plan/1.0",
                "plan_sha256": digest(self.plan.model_dump(mode="json")),
                "reviewer": "offline AI fixture",
                "reviewer_kind": "ai",
                "redaction_confirmed": True,
                "cases": {},
            }
            for case in self.plan.cases[:10]:
                instance = (
                    complete_case(self.plan, case)
                    if case.scenario != "foreign_order"
                    else make_collector(self.plan, case, model_id="fake", scripted=True)
                )
                raw = json.dumps(instance.raw()).encode()
                path = recordings / case.case_id
                path.mkdir()
                (path / "raw.json").write_bytes(raw)
                decisions["cases"][case.case_id] = {
                    "raw_sha256": hashlib.sha256(raw).hexdigest(),
                    "decision": "include"
                    if instance.calls
                    else "exclude_from_compilation",
                    "rationale": "offline declaration fixture",
                    "roles": {call["tool"]: call["id"] for call in instance.calls},
                }
            decision_path = directory / "decisions.json"
            decision_path.write_text(json.dumps(decisions))
            args = [
                str(PLAN_PATH),
                str(recordings),
                str(decision_path),
                "--output-dir",
                str(directory / "reviewed"),
            ]
            with redirect_stdout(StringIO()):
                self.assertEqual(contract_main(args), 0)
            data = json.loads(
                (directory / "reviewed/compile-01/reviewed.json").read_text()
            )
            self.assertEqual(data["metadata"]["reviewer_kind"], "ai")
            self.assertEqual(data["metadata"]["human_review_minutes"], 0)
            self.assertEqual(
                data["runs"][0]["metadata"]["review_minutes_kind"],
                "automated_contract_check_wall_time",
            )
            self.assertFalse((directory / "reviewed/compile-10/reviewed.json").exists())
            build_args = [
                str(directory / "reviewed" / case.case_id / "reviewed.json")
                for case in self.plan.cases[:9]
            ]
            with redirect_stdout(StringIO()):
                self.assertEqual(
                    build_main(
                        build_args
                        + [
                            "--dataset-id",
                            "offline-final-compile",
                            "--output-dir",
                            str(directory / "build"),
                        ]
                    ),
                    0,
                )
                self.assertEqual(
                    freeze_main(
                        [
                            str(PLAN_PATH),
                            "--workflow",
                            str(directory / "build/workflow.json"),
                            "--compile",
                            str(directory / "build/compile.json"),
                            "--review-plan",
                            str(decision_path),
                            "--output-dir",
                            str(directory / "final"),
                            "--confirm-unseen-test",
                        ]
                    ),
                    0,
                )
            bundle = json.loads((directory / "final/report-freeze.json").read_text())
            self.assertEqual(len(bundle["reviewed_included_cases"]), 9)
            self.assertEqual(bundle["reviewed_excluded_cases"], ["compile-10"])
            self.assertEqual(len(bundle["report_source_sha256"]), 64)
            with redirect_stderr(StringIO()), self.assertRaises(SystemExit):
                contract_main(args)
            del decisions["cases"]["compile-10"]
            decision_path.write_text(json.dumps(decisions))
            args[-1] = str(directory / "incomplete")
            with redirect_stderr(StringIO()), self.assertRaises(SystemExit):
                contract_main(args)


if __name__ == "__main__":
    unittest.main()
