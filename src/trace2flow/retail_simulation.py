"""Independent local execution of the reviewed tau retail workflow shape."""

from __future__ import annotations

import copy
import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Literal

from pydantic import Field, JsonValue, TypeAdapter, model_validator

from .ir import WorkflowIR
from .models import StrictModel
from .runtime import ToolRegistry
from .simulation import (
    StateChange,
    execute_local,
    state_diff,
)

RETAIL_TOOLS = frozenset(
    {
        "find_user_id_by_name_zip",
        "get_order_details",
        "get_product_details",
        "modify_pending_order_items",
    }
)


class RetailState(StrictModel):
    """Fresh simulator fixtures; only ``orders`` are mutable."""

    users: dict[str, dict[str, JsonValue]]
    orders: dict[str, dict[str, JsonValue]]
    products: dict[str, dict[str, JsonValue]]


class RetailSimulationCase(StrictModel):
    id: str
    task_input: dict[str, JsonValue]
    initial_state: RetailState
    expected_final_output: JsonValue
    expected_orders_after: dict[str, dict[str, JsonValue]]


class RetailSimulationSuite(StrictModel):
    schema_version: Literal["retail-simulation-suite/1.0"] = (
        "retail-simulation-suite/1.0"
    )
    source_dataset_id: str
    synthetic_data: Literal[True] = True
    recorded_response_replay: Literal[False] = False
    cases: list[RetailSimulationCase] = Field(min_length=1)

    @model_validator(mode="after")
    def validate_unique_cases(self) -> RetailSimulationSuite:
        case_ids = [case.id for case in self.cases]
        if len(case_ids) != len(set(case_ids)):
            raise ValueError("retail simulation case ids must be unique")
        return self


class RetailVerificationCaseResult(StrictModel):
    case_id: str
    status: Literal["passed", "failed", "error"]
    final_output_match: bool
    state_match: bool
    expected_final_output: JsonValue
    actual_final_output: JsonValue = None
    expected_changes: list[StateChange]
    actual_changes: list[StateChange]
    error: str | None = None


class RetailVerificationReport(StrictModel):
    schema_version: Literal["retail-verification-report/1.0"] = (
        "retail-verification-report/1.0"
    )
    validation_scope: Literal[
        "independent_local_simulation_of_recorded_structure"
    ] = "independent_local_simulation_of_recorded_structure"
    synthetic_execution_data: Literal[True] = True
    recorded_structure_source: Literal[True] = True
    recorded_response_replay_used: Literal[False] = False
    source_dataset_id: str
    workflow_id: str
    cases: list[RetailVerificationCaseResult]
    passed: bool


_SUITE_ADAPTER = TypeAdapter(RetailSimulationSuite)


def load_retail_suite(path: str | Path) -> RetailSimulationSuite:
    return _SUITE_ADAPTER.validate_json(Path(path).read_text(encoding="utf-8"), strict=True)


def retail_verification_report_json(report: RetailVerificationReport) -> str:
    return (
        json.dumps(
            report.model_dump(mode="json"),
            ensure_ascii=False,
            allow_nan=False,
            indent=2,
            sort_keys=True,
        )
        + "\n"
    )


def _token(value: JsonValue) -> str:
    return json.dumps(
        value,
        ensure_ascii=False,
        allow_nan=False,
        separators=(",", ":"),
        sort_keys=True,
    )


@dataclass
class RetailSimulator:
    """Four allowlisted in-memory tools; no network or payment operation exists."""

    users: dict[str, dict[str, JsonValue]]
    orders: dict[str, dict[str, JsonValue]]
    products: dict[str, dict[str, JsonValue]]
    inspected_order_ids: set[str] = field(default_factory=set)
    inspected_product_ids: set[str] = field(default_factory=set)

    @classmethod
    def for_state(cls, state: RetailState) -> RetailSimulator:
        return cls(
            users=copy.deepcopy(state.users),
            orders=copy.deepcopy(state.orders),
            products=copy.deepcopy(state.products),
        )

    def snapshot(self) -> dict[str, JsonValue]:
        """Capture the complete mutable collection, not only changed fields."""

        return {"orders": copy.deepcopy(self.orders)}

    def registry(self) -> ToolRegistry:
        return ToolRegistry(
            {
                "find_user_id_by_name_zip": self.find_user_id_by_name_zip,
                "get_order_details": self.get_order_details,
                "get_product_details": self.get_product_details,
                "modify_pending_order_items": self.modify_pending_order_items,
            }
        )

    def find_user_id_by_name_zip(
        self,
        first_name: str,
        last_name: str,
        zip: str,
    ) -> JsonValue:
        matches = [
            user_id
            for user_id, user in self.users.items()
            if user.get("first_name") == first_name
            and user.get("last_name") == last_name
            and user.get("zip") == zip
        ]
        if len(matches) != 1:
            raise KeyError("local user lookup must resolve exactly one user")
        return matches[0]

    def get_order_details(self, order_id: str) -> JsonValue:
        if order_id not in self.orders:
            raise KeyError(f"unknown local order '{order_id}'")
        self.inspected_order_ids.add(order_id)
        return copy.deepcopy(self.orders[order_id])

    def get_product_details(self, product_id: str) -> JsonValue:
        if product_id not in self.products:
            raise KeyError(f"unknown local product '{product_id}'")
        self.inspected_product_ids.add(product_id)
        return copy.deepcopy(self.products[product_id])

    def modify_pending_order_items(
        self,
        item_ids: list[str],
        new_item_ids: list[str],
        order_id: str,
        payment_method_id: str,
    ) -> JsonValue:
        if not item_ids or len(item_ids) != len(new_item_ids):
            raise ValueError("old and new item ids must be non-empty equal-length lists")
        if len(item_ids) != len(set(item_ids)):
            raise ValueError("an order item cannot be replaced more than once")
        if order_id not in self.orders:
            raise KeyError(f"unknown local order '{order_id}'")
        if order_id not in self.inspected_order_ids:
            raise ValueError("local order must be inspected before modification")

        updated = copy.deepcopy(self.orders[order_id])
        if updated.get("status") != "pending":
            raise ValueError("only pending local orders can be modified")
        history = updated.get("payment_history")
        items = updated.get("items")
        if not isinstance(history, list) or not isinstance(items, list):
            raise TypeError("local order must contain item and payment history lists")
        if not any(
            isinstance(entry, dict)
            and entry.get("payment_method_id") == payment_method_id
            for entry in history
        ):
            raise ValueError("payment method is not attached to the local order")

        price_difference = 0.0
        for old_item_id, new_item_id in zip(item_ids, new_item_ids, strict=True):
            matching_indexes = [
                index
                for index, item in enumerate(items)
                if isinstance(item, dict) and item.get("item_id") == old_item_id
            ]
            if len(matching_indexes) != 1:
                raise KeyError(f"old item '{old_item_id}' must occur exactly once")
            index = matching_indexes[0]
            old_item = items[index]
            product_id = old_item.get("product_id")
            product = self.products.get(product_id) if isinstance(product_id, str) else None
            if product_id not in self.inspected_product_ids:
                raise ValueError("local product must be inspected before modification")
            variants = product.get("variants") if isinstance(product, dict) else None
            new_variant = variants.get(new_item_id) if isinstance(variants, dict) else None
            if not isinstance(new_variant, dict) or new_variant.get("available") is not True:
                raise ValueError(
                    f"new item '{new_item_id}' is not an available variant of '{product_id}'"
                )
            old_price = old_item.get("price")
            new_price = new_variant.get("price")
            if isinstance(old_price, bool) or not isinstance(old_price, (int, float)):
                raise TypeError("old item price must be numeric")
            if isinstance(new_price, bool) or not isinstance(new_price, (int, float)):
                raise TypeError("new item price must be numeric")
            price_difference += float(old_price) - float(new_price)
            items[index] = {
                "name": product.get("name"),
                "product_id": product_id,
                "item_id": new_item_id,
                "price": new_price,
                "options": copy.deepcopy(new_variant.get("options", {})),
            }

        adjustment = round(price_difference, 2)
        if adjustment:
            history.append(
                {
                    "transaction_type": "refund" if adjustment > 0 else "payment",
                    "amount": abs(adjustment),
                    "payment_method_id": payment_method_id,
                }
            )
        updated["status"] = "pending (item modified)"
        self.orders[order_id] = updated
        return copy.deepcopy(updated)


def verify_retail_workflow(
    workflow: WorkflowIR,
    suite: RetailSimulationSuite,
) -> RetailVerificationReport:
    """Execute fresh local cases for a workflow whose structure came from M8."""

    if workflow.source_dataset_id != suite.source_dataset_id:
        raise ValueError("retail suite does not name the workflow source dataset")
    workflow_tools = {node.tool for node in workflow.nodes}
    if workflow_tools != RETAIL_TOOLS:
        raise ValueError("retail workflow must contain exactly the four reviewed tools")

    results: list[RetailVerificationCaseResult] = []
    for case in suite.cases:
        simulator = RetailSimulator.for_state(case.initial_state)
        actual_before = simulator.snapshot()
        expected_after: dict[str, JsonValue] = {
            "orders": copy.deepcopy(case.expected_orders_after)
        }
        expected_changes = state_diff(actual_before, expected_after)
        try:
            execution = execute_local(workflow, case.task_input, simulator.registry())
            actual_after = simulator.snapshot()
            actual_changes = state_diff(actual_before, actual_after)
            output_match = _token(execution.final_output) == _token(
                case.expected_final_output
            )
            state_match = _token(actual_after) == _token(expected_after)
            results.append(
                RetailVerificationCaseResult(
                    case_id=case.id,
                    status="passed" if output_match and state_match else "failed",
                    final_output_match=output_match,
                    state_match=state_match,
                    expected_final_output=case.expected_final_output,
                    actual_final_output=execution.final_output,
                    expected_changes=expected_changes,
                    actual_changes=actual_changes,
                )
            )
        except Exception as exc:  # noqa: BLE001 - controlled failure becomes evidence
            results.append(
                RetailVerificationCaseResult(
                    case_id=case.id,
                    status="error",
                    final_output_match=False,
                    state_match=False,
                    expected_final_output=case.expected_final_output,
                    expected_changes=expected_changes,
                    actual_changes=state_diff(actual_before, simulator.snapshot()),
                    error=f"{type(exc).__name__}: {exc}",
                )
            )

    return RetailVerificationReport(
        source_dataset_id=suite.source_dataset_id,
        workflow_id=workflow.workflow_id,
        cases=results,
        passed=bool(results) and all(result.status == "passed" for result in results),
    )
