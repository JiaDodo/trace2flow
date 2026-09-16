import json
import tempfile
import unittest
from pathlib import Path

from pydantic import ValidationError

from trace2flow.tau3_corpus import (
    SourceFile,
    Tau3CorpusError,
    Tau3RetailManifest,
    build_manifest,
    manifest_json,
    write_manifest_exclusive,
)

ROOT = Path(__file__).resolve().parents[1]


def task(task_id: str, entity_id: str | None = None) -> dict:
    actions = [
        {
            "action_id": f"{task_id}_0",
            "name": "get_order_details",
            "arguments": {"order_id": entity_id or f"order-{task_id}"},
            "info": None,
        },
        {
            "action_id": f"{task_id}_1",
            "name": "cancel_pending_order",
            "arguments": {
                "order_id": entity_id or f"order-{task_id}",
                "reason": "changed mind",
            },
            "info": None,
        },
    ]
    return {
        "id": task_id,
        "description": {"purpose": None},
        "user_scenario": {
            "instructions": {"reason_for_call": f"private oracle text {task_id}"}
        },
        "initial_state": None,
        "evaluation_criteria": {
            "actions": actions,
            "communicate_info": [],
            "nl_assertions": None,
            "reward_basis": ["DB", "NL_ASSERTION"],
        },
    }


def fixture_documents() -> tuple[list[dict], dict]:
    tasks = [task(str(index)) for index in range(114)]
    # Two train tasks share an entity and therefore must remain in one role.
    tasks[0] = task("0", "shared-order")
    tasks[1] = task("1", "shared-order")
    return tasks, {
        "train": [str(index) for index in range(74)],
        "test": [str(index) for index in range(74, 114)],
        "base": [str(index) for index in range(114)],
    }


class Tau3CorpusTests(unittest.TestCase):
    def build(self) -> Tau3RetailManifest:
        tasks, split = fixture_documents()
        return build_manifest(
            tasks,
            split,
            [SourceFile(path="tasks.json", sha256="a" * 64)],
        )

    def test_inventory_seals_test_oracles_and_preserves_counts(self):
        manifest = self.build()
        self.assertEqual(manifest.task_count, 114)
        self.assertEqual(manifest.official_train_count, 74)
        self.assertEqual(manifest.sealed_test.task_count, 40)
        self.assertEqual(manifest.compile_count + manifest.development_count, 74)
        serialized = manifest_json(manifest)
        self.assertNotIn("private oracle text 74", serialized)
        self.assertNotIn("evaluation_criteria", serialized)
        self.assertFalse(manifest.sealed_test.oracle_fields_exported)

    def test_shared_entities_never_cross_train_side_roles(self):
        manifest = self.build()
        by_id = {item.task_id: item for item in manifest.train_tasks}
        self.assertEqual(by_id["0"].entity_group_sha256, by_id["1"].entity_group_sha256)
        self.assertEqual(by_id["0"].role, by_id["1"].role)
        roles_by_group: dict[str, set[str]] = {}
        for item in manifest.train_tasks:
            roles_by_group.setdefault(item.entity_group_sha256, set()).add(item.role)
        self.assertTrue(all(len(roles) == 1 for roles in roles_by_group.values()))

    def test_manifest_rejects_partition_overlap(self):
        tasks, split = fixture_documents()
        split["test"][0] = "0"
        with self.assertRaisesRegex(Tau3CorpusError, "overlap"):
            build_manifest(tasks, split, [])

    def test_manifest_rejects_missing_base_task(self):
        tasks, split = fixture_documents()
        split["base"] = split["base"][:-1]
        with self.assertRaisesRegex(Tau3CorpusError, "base partition"):
            build_manifest(tasks, split, [])

    def test_model_rejects_group_crossing_after_tamper(self):
        payload = self.build().model_dump(mode="json")
        shared = payload["train_tasks"][0]["entity_group_sha256"]
        matching = [
            item for item in payload["train_tasks"] if item["entity_group_sha256"] == shared
        ]
        matching[0]["role"] = "compile"
        matching[1]["role"] = "development"
        payload["compile_count"] = sum(
            item["role"] == "compile" for item in payload["train_tasks"]
        )
        payload["development_count"] = sum(
            item["role"] == "development" for item in payload["train_tasks"]
        )
        with self.assertRaisesRegex(ValidationError, "entity-connected group"):
            Tau3RetailManifest.model_validate(payload)

    def test_manifest_write_is_exclusive(self):
        with tempfile.TemporaryDirectory() as directory:
            output = Path(directory) / "manifest.json"
            manifest = self.build()
            write_manifest_exclusive(manifest, output)
            parsed = json.loads(output.read_text(encoding="utf-8"))
            self.assertEqual(parsed["schema_version"], "tau3-retail-corpus-manifest/1.0")
            with self.assertRaises(FileExistsError):
                write_manifest_exclusive(manifest, output)

    def test_checked_in_inventory_and_pilot_report_are_public_safe(self):
        directory = ROOT / "examples" / "tau3-retail-v1"
        manifest_text = (directory / "manifest.json").read_text(encoding="utf-8")
        manifest = Tau3RetailManifest.model_validate_json(manifest_text)
        self.assertEqual((manifest.compile_count, manifest.development_count), (48, 26))
        self.assertEqual(manifest.sealed_test.task_count, 40)
        self.assertNotIn("user_scenario", manifest_text)
        self.assertNotIn("evaluation_criteria", manifest_text)

        pilot_text = (directory / "pilot-report.json").read_text(encoding="utf-8")
        pilot = json.loads(pilot_text)
        self.assertEqual(len(pilot["attempts"]), 3)
        self.assertEqual(pilot["attempts"][-1]["reward"], 0.0)
        self.assertFalse(pilot["raw_results_committed"])
        for forbidden in (
            "error_traceback",
            "api_key",
            "payment_method_id",
            "order_id",
            "reason_for_call",
        ):
            self.assertNotIn(forbidden, pilot_text.lower())


if __name__ == "__main__":
    unittest.main()
