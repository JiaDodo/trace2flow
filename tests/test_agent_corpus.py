"""M11 synthetic mechanics only; no paid calls or held-out model results."""

import hashlib
import json
import tempfile
import unittest
from contextlib import redirect_stderr, redirect_stdout
from io import StringIO
from pathlib import Path
from unittest.mock import patch

from pydantic import ValidationError

from trace2flow.agent_corpus import (
    CorpusPlan,
    assert_record_case,
    digest,
    freeze,
    load_plan,
    make_collector,
    materialize,
    verify_freeze,
)
from trace2flow.agent_corpus import (
    main as corpus_main,
)
from trace2flow.agent_evaluation import (
    evaluate_inventory,
    evaluate_record,
    evaluate_workflow,
)
from trace2flow.agent_evaluation import main as evaluation_main
from trace2flow.agent_review import (
    RecordingReview,
    build_main,
    combine_reviewed,
    declared_resolution,
    draft_review,
    review_recording,
)
from trace2flow.candidate import mine_candidate_dag
from trace2flow.io import load_trace_dataset
from trace2flow.ir import build_workflow_ir, loads_workflow_ir

PLAN_PATH = (
    Path(__file__).resolve().parents[1]
    / "examples/customer-support-agent/corpus-plan.json"
)


def complete_case(plan, case):
    instance = make_collector(plan, case, model_id="scripted-offline", scripted=True)
    task = instance.task
    instance.dispatch("customer", "lookup_customer", {"customer_id": task.customer_id})
    order = instance.dispatch(
        "order",
        "lookup_order",
        {"order_id": task.order_id, "customer_id": task.customer_id},
    )
    classification = instance.dispatch(
        "classify",
        "classify_issue",
        {
            "ticket_text": task.ticket_text,
            "order_status": order["status"],
            "delivered": order["delivered"],
            "damaged": order["damaged"],
            "duplicate_charge": order["duplicate_charge"],
        },
    )
    advice = instance.dispatch(
        "recommend", "recommend_action", {**classification, "policy_version": "v1"}
    )
    instance.dispatch(
        "update",
        "update_ticket",
        {
            "ticket_id": task.ticket_id,
            "status": advice["status"],
            "recommendation": advice["recommendation"],
            "issue_type": advice["issue_type"],
        },
    )
    instance.ending = "model_finished"
    return instance


def declaration(plan, instance):
    # Explicit fixture review of these known occurrence IDs, not a production matcher.
    data = instance.normalized()
    raw = json.dumps(instance.raw(), ensure_ascii=False).encode()
    calls = {}
    input_parameters = {
        "customer": {"customer_id": "customer_id"},
        "order": {"customer_id": "customer_id", "order_id": "order_id"},
        "classify": {"ticket_text": "ticket_text"},
        "update": {"ticket_id": "ticket_id"},
    }
    output_parameters = {
        "classify": {
            key: ("order", "status" if key == "order_status" else key)
            for key in ("order_status", "delivered", "damaged", "duplicate_charge")
        },
        "recommend": {key: ("classify", key) for key in ("issue_type", "eligible")},
        "update": {
            key: ("recommend", key)
            for key in ("status", "recommendation", "issue_type")
        },
    }
    for step in data.runs[0].steps:
        bindings, dependencies = {}, []
        for parameter in step.params:
            if parameter in input_parameters.get(step.id, {}):
                bindings[parameter] = {
                    "kind": "task_input",
                    "path": [input_parameters[step.id][parameter]],
                    "rationale": "fixture reviewer explicitly declares task input",
                }
            elif parameter in output_parameters.get(step.id, {}):
                source, path = output_parameters[step.id][parameter]
                bindings[parameter] = {
                    "kind": "tool_output",
                    "source_call_id": source,
                    "path": [path],
                    "rationale": "fixture reviewer explicitly declares output path",
                }
                if source not in dependencies:
                    dependencies.append(source)
            else:
                bindings[parameter] = {
                    "kind": "constant",
                    "value": "v1",
                    "rationale": "fixture policy explicitly declares v1",
                }
        calls[step.id] = {
            "depends_on": dependencies,
            "side_effects": [
                effect.model_dump(mode="json") for effect in step.side_effects
            ],
            "bindings": bindings,
        }
    review = RecordingReview.model_validate(
        {
            "schema_version": "agent-recording-review/1.0",
            "raw_sha256": hashlib.sha256(raw).hexdigest(),
            "plan_sha256": digest(plan.model_dump(mode="json")),
            "reviewer": "synthetic fixture declaration",
            "redaction_confirmed": True,
            "review_minutes": 0.0,
            "decision": "include",
            "rationale": "controlled offline regression only",
            "calls": calls,
        }
    )
    return raw, review


class AgentCorpusTests(unittest.TestCase):
    def setUp(self):
        self.plan = load_plan(PLAN_PATH)
        self.normal_case = self.plan.cases[0]

    def test_counts_group_and_entity_disjointness(self):
        self.assertEqual(
            {
                role: sum(case.partition == role for case in self.plan.cases)
                for role in ("compile", "development", "test")
            },
            {"compile": 10, "development": 8, "test": 12},
        )
        role_entities = {role: set() for role in ("compile", "development", "test")}
        for case in self.plan.cases:
            state = materialize(case)["state_before"]
            role_entities[case.partition].update(
                (kind, key) for kind, objects in state.items() for key in objects
            )
        self.assertFalse(role_entities["compile"] & role_entities["test"])
        self.assertFalse(role_entities["development"] & role_entities["test"])
        payload = self.plan.model_dump(mode="json")
        payload["cases"][-1]["group_id"] = payload["cases"][0]["group_id"]
        with self.assertRaisesRegex(ValidationError, "crosses partitions"):
            CorpusPlan.model_validate(payload)

    def test_identifier_collision_and_duplicate_case_rejected(self):
        payload = self.plan.model_dump(mode="json")
        payload["cases"][-1]["group_id"] = "other-compile-01"
        with self.assertRaisesRegex(ValidationError, "entity identity"):
            CorpusPlan.model_validate(payload)
        payload = self.plan.model_dump(mode="json")
        payload["cases"][-1]["case_id"] = payload["cases"][0]["case_id"]
        with self.assertRaisesRegex(ValidationError, "duplicate case"):
            CorpusPlan.model_validate(payload)

    def test_freeze_detects_mutation_and_never_overwrites(self):
        with tempfile.TemporaryDirectory() as temp:
            directory = Path(temp) / "freeze"
            manifest = freeze(self.plan, directory)
            verify_freeze(self.plan, manifest)
            self.assertIn("agent_evaluation.py", manifest["source_sha256"])
            changed = json.loads(json.dumps(manifest))
            changed["source_sha256"]["agent_review.py"] = "0" * 64
            with self.assertRaisesRegex(ValueError, "freeze manifest"):
                verify_freeze(self.plan, changed)
            with self.assertRaises(FileExistsError):
                freeze(self.plan, directory)
            manifest["cases"][0]["partition"] = "test"
            with self.assertRaisesRegex(ValueError, "freeze manifest"):
                verify_freeze(self.plan, manifest)

    def test_input_projection_has_no_oracle_and_test_requires_unlock(self):
        output = StringIO()
        with redirect_stdout(output):
            self.assertEqual(
                corpus_main([str(PLAN_PATH), "--case-id", "compile-01"]), 0
            )
        projected = json.loads(output.getvalue())
        self.assertNotIn("oracle", projected)
        self.assertNotIn("state_before", projected)
        self.assertNotIn("scenario", projected)
        with self.assertRaises(SystemExit), redirect_stderr(StringIO()):
            corpus_main([str(PLAN_PATH), "--case-id", "test-01"])

    def test_no_paid_call_without_explicit_flag(self):
        with (
            tempfile.TemporaryDirectory() as temp,
            patch("trace2flow.agent_corpus.deepseek_model") as model,
        ):
            with redirect_stderr(StringIO()), self.assertRaises(SystemExit):
                corpus_main(
                    [
                        str(PLAN_PATH),
                        "--case-id",
                        "compile-01",
                        "--collect-output",
                        str(Path(temp) / "new"),
                    ]
                )
            model.assert_not_called()

    def test_test_evaluation_requires_unlock_and_manifest_before_reading_results(self):
        for extra in ([], ["--unlock-test"]):
            with (
                patch("trace2flow.agent_evaluation.evaluate_inventory") as evaluator,
                redirect_stderr(StringIO()),
                self.assertRaises(SystemExit),
            ):
                evaluation_main(
                    [str(PLAN_PATH), "/not-collected", "--partition", "test", *extra]
                )
            evaluator.assert_not_called()

    def test_record_typed_state_prompt_and_context_are_bound(self):
        instance = complete_case(self.plan, self.normal_case)
        changes = (
            lambda raw: raw["state_before"]["orders"][instance.task.order_id].update(
                delivered=0
            ),
            lambda raw: raw["collection_context"].update(partition="test"),
            lambda raw: raw.update(prompt_sha256="0" * 64),
            lambda raw: raw["task"].update(ticket_text="changed"),
        )
        for change in changes:
            raw = instance.raw()
            change(raw)
            with self.assertRaises(ValueError):
                assert_record_case(self.plan, raw)

    def test_draft_is_not_approval_or_inferred_lineage(self):
        instance = complete_case(self.plan, self.normal_case)
        template = draft_review(self.plan, json.dumps(instance.raw()).encode())
        self.assertFalse(template["redaction_confirmed"])
        self.assertEqual(template["reviewer"], "")
        self.assertTrue(
            all(not call["depends_on"] for call in template["calls"].values())
        )
        self.assertTrue(
            all(
                binding["kind"] == "unresolved"
                for call in template["calls"].values()
                for binding in call["bindings"].values()
            )
        )
        with self.assertRaises(ValidationError):
            RecordingReview.model_validate(template)

    def test_collector_environment_isolated_and_answers_independent_of_tools(self):
        with patch(
            "trace2flow.simulation.CustomerSupportSimulator.classify_issue",
            return_value={"wrong": True},
        ):
            self.assertEqual(
                materialize(self.normal_case)["oracle"]["expected_final_output"][
                    "issue_type"
                ],
                "delivery_delay",
            )
        first = make_collector(
            self.plan, self.normal_case, model_id="fake", scripted=True
        )
        second = make_collector(
            self.plan, self.normal_case, model_id="fake", scripted=True
        )
        first.simulator.tickets[first.task.ticket_id]["status"] = "corrupted"
        self.assertEqual(
            second.snapshot()["tickets"][second.task.ticket_id]["status"], "open"
        )
        self.assertNotIn("oracle", first.raw()["task"])

    def test_complete_review_retains_types_and_declared_edges(self):
        instance = complete_case(self.plan, self.normal_case)
        raw, review = declaration(self.plan, instance)
        data = review_recording(self.plan, raw, review)
        self.assertIs(data.runs[0].steps[2].params["delivered"], False)
        self.assertEqual(data.runs[0].steps[2].depends_on, ["order"])
        self.assertEqual(data.runs[0].steps[1].depends_on, [])
        self.assertEqual(data.metadata["import_review_status"], "complete")
        self.assertTrue(data.metadata["binding_resolution_still_required"])

    def test_hash_and_missing_occurrence_or_parameter_rejected(self):
        instance = complete_case(self.plan, self.normal_case)
        raw, review = declaration(self.plan, instance)
        with self.assertRaisesRegex(ValueError, "SHA mismatch"):
            review_recording(self.plan, raw + b" ", review)
        incomplete = review.model_copy(deep=True)
        del incomplete.calls["order"]
        with self.assertRaisesRegex(ValueError, "every distinct"):
            review_recording(self.plan, raw, incomplete)
        incomplete = review.model_copy(deep=True)
        del incomplete.calls["classify"].bindings["delivered"]
        with self.assertRaisesRegex(ValueError, "every parameter"):
            review_recording(self.plan, raw, incomplete)

    def test_weak_values_require_declaration_and_type_mismatch_rejected(self):
        instance = complete_case(self.plan, self.normal_case)
        raw, review = declaration(self.plan, instance)
        review.calls["classify"].bindings["delivered"].kind = "constant"
        review.calls["classify"].bindings["delivered"].source_call_id = None
        review.calls["classify"].bindings["delivered"].path = []
        review.calls["classify"].bindings["delivered"].value = 0
        with self.assertRaisesRegex(ValueError, "typed value"):
            review_recording(self.plan, raw, review)

    def test_future_dependency_and_effect_lie_rejected(self):
        instance = complete_case(self.plan, self.normal_case)
        raw, review = declaration(self.plan, instance)
        future = review.model_copy(deep=True)
        future.calls["order"].depends_on = ["update"]
        with self.assertRaisesRegex(ValueError, "future occurrence"):
            review_recording(self.plan, raw, future)
        payload = review.model_dump(mode="json")
        payload["calls"]["update"]["side_effects"] = [{"kind": "none"}]
        with self.assertRaisesRegex(ValueError, "side effect contradicts"):
            review_recording(self.plan, raw, RecordingReview.model_validate(payload))

    def test_failure_excluded_from_mining_but_still_evaluated(self):
        case = self.plan.cases[9]
        instance = make_collector(self.plan, case, model_id="fake", scripted=True)
        instance.dispatch(
            "order",
            "lookup_order",
            {
                "order_id": instance.task.order_id,
                "customer_id": instance.task.customer_id,
            },
        )
        instance.ending = "model_finished"
        raw, review = declaration(self.plan, instance)
        with self.assertRaisesRegex(ValueError, "incomplete or failed"):
            review_recording(self.plan, raw, review)
        review.decision = "exclude_from_compilation"
        self.assertIsNone(review_recording(self.plan, raw, review))
        report = evaluate_inventory(self.plan, [instance.raw()], "compile")
        self.assertEqual(report["planned_cases"], 10)
        self.assertEqual(report["evaluated_cases"], 1)
        self.assertEqual(report["pending_cases"], 9)
        self.assertFalse(report["score_final"])

    def test_zero_calls_and_duplicate_trials_not_hidden(self):
        case = self.plan.cases[15]
        instance = make_collector(self.plan, case, model_id="fake", scripted=True)
        instance.ending = "model_budget_exhausted"
        report = evaluate_inventory(self.plan, [instance.raw()], "development")
        self.assertEqual(report["evaluated_cases"], 1)
        self.assertEqual(report["correct_cases"], 0)
        with self.assertRaisesRegex(ValueError, "duplicate trial"):
            evaluate_inventory(
                self.plan, [instance.raw(), instance.raw()], "development"
            )

    def test_outcome_corruption_and_unsafe_write_attempt_detected(self):
        instance = complete_case(self.plan, self.normal_case)
        self.assertTrue(evaluate_record(self.plan, instance.raw())["correct"])
        raw = instance.raw()
        raw["calls"][-1]["output"]["status"] = "wrong"
        self.assertFalse(evaluate_record(self.plan, raw)["output_match"])
        raw = instance.raw()
        raw["state_after"]["orders"][instance.task.order_id]["status"] = "wrong"
        self.assertFalse(evaluate_record(self.plan, raw)["complete_state_match"])
        case = self.plan.cases[9]
        failed = make_collector(self.plan, case, model_id="fake", scripted=True)
        failed.dispatch(
            "write",
            "update_ticket",
            {
                "ticket_id": failed.task.ticket_id,
                "status": "pending_review",
                "recommendation": "manual_refund_review",
                "issue_type": "billing_duplicate",
            },
        )
        failed.ending = "model_finished"
        report = evaluate_record(self.plan, failed.raw())
        self.assertTrue(report["unsafe_write_attempt"])
        self.assertFalse(report["correct"])

    def test_real_compiler_reviewed_ir_and_independent_development_execution(self):
        datasets = []
        for case in self.plan.cases[:3]:
            raw, review = declaration(self.plan, complete_case(self.plan, case))
            datasets.append(review_recording(self.plan, raw, review))
        dataset = combine_reviewed(datasets, "offline-reviewed-compile")
        candidate = mine_candidate_dag(dataset)
        unresolved = build_workflow_ir(dataset, candidate)
        self.assertTrue(unresolved.execution_blockers())
        resolution = declared_resolution(dataset, candidate)
        workflow = build_workflow_ir(dataset, candidate, resolution)
        self.assertEqual(workflow.execution_blockers(), [])
        report = evaluate_workflow(self.plan, workflow, "development", dataset)
        self.assertEqual(report["planned_cases"], 8)
        self.assertEqual(report["accepted_cases"], 4)
        self.assertEqual(report["accepted_correct_cases"], 4)
        self.assertEqual(report["unsafe_acceptances"], 0)
        self.assertEqual(report["correct_cases"], 8)
        self.assertEqual(report["coverage"], 0.5)
        broken = dataset.model_copy(deep=True)
        broken.metadata["plan_sha256"] = "0" * 64
        with self.assertRaisesRegex(ValueError, "plan SHA"):
            evaluate_workflow(self.plan, workflow, "development", broken)

    def test_cross_partition_merge_rejected(self):
        raw, review = declaration(self.plan, complete_case(self.plan, self.normal_case))
        first = review_recording(self.plan, raw, review)
        raw, review = declaration(
            self.plan, complete_case(self.plan, self.plan.cases[10])
        )
        second = review_recording(self.plan, raw, review)
        with self.assertRaisesRegex(ValueError, "different corpus partitions"):
            combine_reviewed([first, second], "mixed")

    def test_unresolved_or_disagreeing_declarations_cannot_become_bindings(self):
        datasets = []
        for index, case in enumerate(self.plan.cases[:3]):
            raw, review = declaration(self.plan, complete_case(self.plan, case))
            if index == 1:
                binding = review.calls["classify"].bindings["delivered"]
                binding.kind, binding.path, binding.source_call_id = (
                    "unresolved",
                    [],
                    None,
                )
                review.calls["order"].bindings["customer_id"].kind = "constant"
                review.calls["order"].bindings["customer_id"].path = []
                review.calls["order"].bindings["customer_id"].value = materialize(case)[
                    "task"
                ]["customer_id"]
            datasets.append(review_recording(self.plan, raw, review))
        dataset = combine_reviewed(datasets, "ambiguous-reviewed")
        candidate = mine_candidate_dag(dataset)
        resolution = declared_resolution(dataset, candidate)
        pairs = {
            (item.node_id, item.parameter) for item in resolution.binding_overrides
        }
        node_for = {node.tool: node.id for node in candidate.nodes}
        self.assertNotIn((node_for["classify_issue"], "delivered"), pairs)
        self.assertNotIn((node_for["lookup_order"], "customer_id"), pairs)
        self.assertTrue(
            build_workflow_ir(dataset, candidate, resolution).execution_blockers()
        )
        candidate.source_sha256 = "0" * 64
        with self.assertRaisesRegex(ValueError, "reviewed candidate source"):
            declared_resolution(dataset, candidate)

    def test_build_cli_writes_real_content_and_does_not_overwrite(self):
        with tempfile.TemporaryDirectory() as temp:
            directory = Path(temp)
            paths = []
            for case in self.plan.cases[:3]:
                raw, review = declaration(self.plan, complete_case(self.plan, case))
                data = review_recording(self.plan, raw, review)
                path = directory / (case.case_id + ".json")
                # Runtime test artifacts, not source file edits.
                path.write_text(data.model_dump_json())
                paths.append(str(path))
            args = paths + [
                "--dataset-id",
                "cli-reviewed",
                "--output-dir",
                str(directory / "build"),
            ]
            with redirect_stdout(StringIO()):
                self.assertEqual(build_main(args), 0)
            workflow = json.loads((directory / "build/workflow.json").read_text())
            self.assertEqual(len(workflow["nodes"]), 5)
            self.assertEqual(workflow["source_dataset_id"], "cli-reviewed")
            report = evaluate_workflow(
                self.plan,
                loads_workflow_ir((directory / "build/workflow.json").read_text()),
                "development",
                load_trace_dataset(directory / "build/compile.json"),
            )
            self.assertEqual(report["accepted_correct_cases"], 4)
            workflow_ir = loads_workflow_ir(
                (directory / "build/workflow.json").read_text()
            )
            compile_data = load_trace_dataset(directory / "build/compile.json")
            manifest = freeze(
                self.plan,
                directory / "final-freeze",
                workflow=workflow_ir,
                compile_dataset=compile_data,
            )
            self.assertEqual(
                manifest["workflow_sha256"], digest(workflow_ir.model_dump(mode="json"))
            )
            self.assertEqual(
                manifest["compile_sha256"], digest(compile_data.model_dump(mode="json"))
            )
            workflow_ir.source_sha256 = "0" * 64
            with self.assertRaisesRegex(ValueError, "final workflow"):
                freeze(
                    self.plan,
                    directory / "invalid-freeze",
                    workflow=workflow_ir,
                    compile_dataset=compile_data,
                )
            with redirect_stderr(StringIO()), self.assertRaises(SystemExit):
                build_main(args)


if __name__ == "__main__":
    unittest.main()
