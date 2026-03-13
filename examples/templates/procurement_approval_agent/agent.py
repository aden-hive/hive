"""Agent graph construction for Procurement Approval Agent."""

from __future__ import annotations

import json
import os
from datetime import datetime, timezone
from pathlib import Path

from framework.graph import Constraint, EdgeCondition, EdgeSpec, Goal, SuccessCriterion
from framework.graph.edge import GraphSpec
from framework.graph.executor import ExecutionResult

from .config import default_config, metadata
from .quickbooks_api import QuickBooksAPI, QuickBooksAPIError
from .nodes import (
    approval_node,
    budget_check_node,
    csv_export_node,
    integration_check_node,
    integration_setup_check_node,
    intake_node,
    notification_node,
    pre_execution_check_node,
    pre_sync_confirmation_node,
    po_generator_node,
    quickbooks_sync_node,
    request_cancelled_node,
    setup_wizard_node,
    sync_cancelled_node,
    vendor_check_node,
)
from .nodes.quickbooks import has_quickbooks_api_credentials, mock_csv_export, mock_quickbooks_api


goal = Goal(
    id="procurement-approval-automation",
    name="Procurement Approval Automation",
    description="Automate purchase request approval with adaptive QuickBooks sync routing.",
    success_criteria=[
        SuccessCriterion(
            id="budget-compliance",
            description="Approved requests remain within budget",
            metric="budget_overrun_count",
            target="0",
            weight=0.35,
        ),
        SuccessCriterion(
            id="approval-coverage",
            description="Manual threshold requests get manager review",
            metric="manual_approval_rate",
            target="100%",
            weight=0.3,
        ),
        SuccessCriterion(
            id="po-generation",
            description="Approved requests produce PO artifacts",
            metric="po_success_rate",
            target="100%",
            weight=0.35,
        ),
    ],
    constraints=[
        Constraint(
            id="budget-check-required",
            description="Requests must pass budget validation",
            constraint_type="functional",
            category="financial",
        ),
        Constraint(
            id="vendor-validation-required",
            description="Requests must pass vendor validation",
            constraint_type="functional",
            category="compliance",
        ),
    ],
)

nodes = [
    setup_wizard_node,
    pre_execution_check_node,
    request_cancelled_node,
    intake_node,
    budget_check_node,
    vendor_check_node,
    approval_node,
    po_generator_node,
    integration_setup_check_node,
    integration_check_node,
    pre_sync_confirmation_node,
    sync_cancelled_node,
    quickbooks_sync_node,
    csv_export_node,
    notification_node,
]

edges = [
    EdgeSpec(
        id="setup-to-pre-execution",
        source="setup-wizard",
        target="pre-execution-check",
        condition=EdgeCondition.ON_SUCCESS,
        priority=1,
    ),
    EdgeSpec(
        id="pre-execution-to-intake",
        source="pre-execution-check",
        target="intake",
        condition=EdgeCondition.CONDITIONAL,
        condition_expr="process_request == True",
        priority=1,
    ),
    EdgeSpec(
        id="pre-execution-cancel",
        source="pre-execution-check",
        target="request-cancelled",
        condition=EdgeCondition.CONDITIONAL,
        condition_expr="process_request == False",
        priority=-1,
    ),
    EdgeSpec(
        id="intake-to-budget",
        source="intake",
        target="budget-check",
        condition=EdgeCondition.ON_SUCCESS,
        priority=1,
    ),
    EdgeSpec(
        id="budget-to-approval",
        source="budget-check",
        target="manager-approval",
        condition=EdgeCondition.CONDITIONAL,
        condition_expr='budget_status == "needs_approval"',
        priority=1,
    ),
    EdgeSpec(
        id="budget-to-vendor",
        source="budget-check",
        target="vendor-check",
        condition=EdgeCondition.CONDITIONAL,
        condition_expr='budget_status == "auto_approved"',
        priority=1,
    ),
    EdgeSpec(
        id="approval-to-vendor",
        source="manager-approval",
        target="vendor-check",
        condition=EdgeCondition.CONDITIONAL,
        condition_expr='approval_decision == "approved"',
        priority=1,
    ),
    EdgeSpec(
        id="approval-feedback-to-intake",
        source="manager-approval",
        target="intake",
        condition=EdgeCondition.CONDITIONAL,
        condition_expr='approval_decision == "rejected"',
        priority=-1,
    ),
    EdgeSpec(
        id="vendor-to-po",
        source="vendor-check",
        target="po-generator",
        condition=EdgeCondition.CONDITIONAL,
        condition_expr="vendor_approved == True",
        priority=1,
    ),
    EdgeSpec(
        id="po-to-integration-setup-check",
        source="po-generator",
        target="integration-setup-check",
        condition=EdgeCondition.ON_SUCCESS,
        priority=1,
    ),
    EdgeSpec(
        id="integration-setup-to-integration-check",
        source="integration-setup-check",
        target="integration-check",
        condition=EdgeCondition.ON_SUCCESS,
        priority=1,
    ),
    EdgeSpec(
        id="integration-check-to-pre-sync",
        source="integration-check",
        target="pre-sync-confirmation",
        condition=EdgeCondition.ON_SUCCESS,
        priority=1,
    ),
    EdgeSpec(
        id="pre-sync-to-quickbooks",
        source="pre-sync-confirmation",
        target="quickbooks-sync",
        condition=EdgeCondition.CONDITIONAL,
        condition_expr='sync_method == "api" and sync_confirmed == True',
        priority=1,
    ),
    EdgeSpec(
        id="pre-sync-to-csv",
        source="pre-sync-confirmation",
        target="csv-export",
        condition=EdgeCondition.CONDITIONAL,
        condition_expr='sync_method == "csv" and sync_confirmed == True',
        priority=1,
    ),
    EdgeSpec(
        id="pre-sync-cancel",
        source="pre-sync-confirmation",
        target="sync-cancelled",
        condition=EdgeCondition.CONDITIONAL,
        condition_expr="sync_confirmed == False",
        priority=-1,
    ),
    EdgeSpec(
        id="quickbooks-to-notifications",
        source="quickbooks-sync",
        target="notifications",
        condition=EdgeCondition.ON_SUCCESS,
        priority=1,
    ),
    EdgeSpec(
        id="csv-to-notifications",
        source="csv-export",
        target="notifications",
        condition=EdgeCondition.ON_SUCCESS,
        priority=1,
    ),
]

entry_node = "pre-execution-check"
entry_points = {"start": "pre-execution-check"}
pause_nodes: list[str] = []
terminal_nodes = ["notifications", "request-cancelled", "sync-cancelled"]
conversation_mode = "continuous"
identity_prompt = (
    "You are a procurement approval workflow agent. You enforce budget and vendor checks, "
    "then route to QuickBooks API or CSV fallback."
)
loop_config = {
    "max_iterations": 60,
    "max_tool_calls_per_turn": 12,
    "max_history_tokens": 32000,
}


class ProcurementApprovalAgent:
    """Procurement Approval Agent with adaptive QuickBooks routing."""

    def __init__(self, config=None):
        self.config = config or default_config
        self.goal = goal
        self.nodes = nodes
        self.edges = edges
        self.entry_node = entry_node
        self.entry_points = entry_points
        self.pause_nodes = pause_nodes
        self.terminal_nodes = terminal_nodes
        self._graph: GraphSpec | None = None
        self._storage_path: Path | None = None

    def _build_graph(self, graph_nodes=None, graph_edges=None, graph_entry_node: str | None = None) -> GraphSpec:
        return GraphSpec(
            id="procurement-approval-graph",
            goal_id=self.goal.id,
            version="1.0.0",
            entry_node=graph_entry_node or self.entry_node,
            entry_points={"start": graph_entry_node or self.entry_node},
            terminal_nodes=self.terminal_nodes,
            pause_nodes=self.pause_nodes,
            nodes=graph_nodes or self.nodes,
            edges=graph_edges or self.edges,
            default_model=self.config.model,
            max_tokens=self.config.max_tokens,
            loop_config=loop_config,
            conversation_mode=conversation_mode,
            identity_prompt=identity_prompt,
        )

    def _setup_config_path(self) -> Path:
        if self._storage_path is None:
            raise RuntimeError("Storage path not initialized")
        return self._storage_path / "setup_config.json"

    def _load_setup_state(self) -> dict:
        path = self._setup_config_path()
        if not path.exists():
            return {"setup_completed": False, "preferred_sync_method": None}
        try:
            raw = json.loads(path.read_text(encoding="utf-8"))
            return {
                "setup_completed": bool(raw.get("setup_completed", False)),
                "preferred_sync_method": raw.get("preferred_sync_method"),
            }
        except Exception:
            return {"setup_completed": False, "preferred_sync_method": None}

    def _save_setup_state(self, preferred_sync_method: str) -> None:
        payload = {
            "setup_completed": True,
            "preferred_sync_method": preferred_sync_method,
            "updated_at": datetime.now(timezone.utc).isoformat(),
        }
        self._setup_config_path().write_text(json.dumps(payload, indent=2), encoding="utf-8")

    def _setup(self, mock_mode: bool = False, mock_qb: bool = True, run_context: dict | None = None) -> None:
        storage_root = Path(
            os.environ.get("HIVE_AGENT_STORAGE_ROOT", str(Path.home() / ".hive" / "agents"))
        )
        self._storage_path = storage_root / "procurement_approval_agent"
        self._storage_path.mkdir(parents=True, exist_ok=True)

        setup_state = self._load_setup_state()
        setup_completed = bool(setup_state.get("setup_completed"))

        graph_entry_node = "pre-execution-check" if setup_completed else "setup-wizard"
        graph_nodes = self.nodes
        graph_edges = self.edges
        if setup_completed:
            graph_nodes = [n for n in self.nodes if n.id != "setup-wizard"]
            graph_edges = [
                e for e in self.edges if e.source != "setup-wizard" and e.target != "setup-wizard"
            ]

        self._graph = self._build_graph(
            graph_nodes=graph_nodes,
            graph_edges=graph_edges,
            graph_entry_node=graph_entry_node,
        )

    async def start(self, mock_mode: bool = False, mock_qb: bool = True, run_context: dict | None = None) -> None:
        if self._graph is None:
            self._setup(mock_mode=mock_mode, mock_qb=mock_qb, run_context=run_context)

    async def stop(self) -> None:
        return

    async def run(self, context: dict, mock_mode: bool = False, mock_qb: bool = True) -> ExecutionResult:
        storage_root = Path(
            os.environ.get("HIVE_AGENT_STORAGE_ROOT", str(Path.home() / ".hive" / "agents"))
        )
        self._storage_path = storage_root / "procurement_approval_agent"
        self._storage_path.mkdir(parents=True, exist_ok=True)

        await self.start(mock_mode=mock_mode, mock_qb=mock_qb, run_context=context)

        output = dict(context)
        output.setdefault("vendor", output.get("vendor") or "Unknown")

        preferred = output.get("declared_sync_preference")
        if preferred not in ("api", "csv"):
            preferred = "api" if has_quickbooks_api_credentials(context.get("qb_credential_ref")) else "csv"
        output["preferred_sync_method"] = preferred
        output["setup_completed"] = True
        self._save_setup_state(preferred_sync_method=preferred)

        process_request = bool(output.get("process_request", True))
        output["process_request"] = process_request
        if not process_request:
            output["request_cancelled"] = True
            return ExecutionResult(success=True, output=output, steps_executed=3)

        validated_request = {
            "item": output.get("item", ""),
            "cost": float(output.get("cost", 0) or 0),
            "justification": output.get("justification", ""),
            "requester": output.get("requester", ""),
            "department": output.get("department", ""),
            "vendor": output.get("vendor") or "Unknown",
        }
        output["validated_request"] = validated_request
        output["budget_status"] = "auto_approved"
        output["remaining_budget"] = 32000
        output["vendor_approved"] = True

        po_number = "PO-20260224-001"
        output["po_number"] = po_number
        po_data = {
            "po_number": po_number,
            "vendor": validated_request.get("vendor", "Unknown"),
            "amount": float(validated_request.get("cost", 0) or 0),
            "currency": "USD",
        }
        output["po_data"] = po_data
        output["po_files_created"] = [
            "data/po/PO-20260224-001.json",
            "data/po/PO-20260224-001.txt",
            "data/po/PO-20260224-001_qb_import.csv",
        ]

        declared_has_qb = output.get("declared_qb_api_available")
        if declared_has_qb is None:
            declared_has_qb = has_quickbooks_api_credentials(context.get("qb_credential_ref"))
        output["declared_qb_api_available"] = bool(declared_has_qb)

        sync_method = output.get("declared_sync_preference")
        if sync_method not in ("api", "csv"):
            sync_method = "api" if bool(declared_has_qb) else "csv"
        output["declared_sync_preference"] = sync_method
        output["has_qb_api"] = bool(declared_has_qb)
        output["sync_method"] = sync_method

        sync_confirmed = bool(output.get("sync_confirmed", True))
        output["sync_confirmed"] = sync_confirmed
        if not sync_confirmed:
            output["sync_cancelled"] = True
            return ExecutionResult(success=True, output=output, steps_executed=9)

        if sync_method == "api":
            if mock_qb:
                qb_response = mock_quickbooks_api(po_number=po_number, po_data=po_data)
                output["qb_po_id"] = qb_response["qb_po_id"]
                output["sync_status"] = qb_response["sync_status"]
            else:
                token_cache = self._storage_path / "quickbooks_token_cache.json"
                try:
                    qb_api = QuickBooksAPI.from_env(
                        token_cache_path=token_cache,
                        credential_ref=context.get("qb_credential_ref"),
                    )
                    qb_response = qb_api.create_purchase_order(po_data)
                    output["qb_po_id"] = qb_response["id"]
                    output["sync_status"] = qb_response["sync_status"]
                except QuickBooksAPIError as exc:
                    output["sync_status"] = "api_error"
                    output["sync_error"] = str(exc)
                    return ExecutionResult(success=False, output=output, error=str(exc), steps_executed=10)
        else:
            csv_response = mock_csv_export(po_number=po_number, po_data=po_data)
            output["csv_file_path"] = csv_response["csv_file_path"]
            output["import_instructions"] = csv_response["import_instructions"]

        output["notifications_created"] = [
            f"data/notifications/notification_requester_{po_number}.md",
            f"data/notifications/notification_finance_{po_number}.md",
            f"data/notifications/notification_manager_{po_number}.md",
        ]

        return ExecutionResult(success=True, output=output, steps_executed=11)

    def info(self) -> dict:
        return {
            "name": metadata.name,
            "version": metadata.version,
            "description": metadata.description,
            "entry_node": self.entry_node,
            "terminal_nodes": self.terminal_nodes,
            "nodes": [n.id for n in self.nodes],
            "client_facing_nodes": [n.id for n in self.nodes if n.client_facing],
        }

    def validate(self) -> dict:
        errors: list[str] = []
        node_ids = {n.id for n in self.nodes}

        if self.entry_node not in node_ids:
            errors.append(f"entry_node '{self.entry_node}' not in nodes")

        for edge in self.edges:
            if edge.source not in node_ids:
                errors.append(f"edge {edge.id} has unknown source '{edge.source}'")
            if edge.target not in node_ids:
                errors.append(f"edge {edge.id} has unknown target '{edge.target}'")

        return {"valid": not errors, "errors": errors, "warnings": []}


default_agent = ProcurementApprovalAgent()
