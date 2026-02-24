from __future__ import annotations

"""
Minimal Document Processing Agent example.

This example shows how to build a small goal-driven agent that:

- Receives raw document text as input.
- Extracts a simple summary.
- Identifies main "entities" (naive heuristic over capitalized words).
- Returns a structured result with summary and entities.

Run with:
    uv run python core/examples/document_processing_agent.py
"""

import asyncio
import re
from pathlib import Path
from typing import Any, Dict, List

from framework.graph import EdgeCondition, EdgeSpec, Goal, GraphSpec, NodeSpec
from framework.graph.executor import ExecutionResult, GraphExecutor
from framework.graph.node import NodeContext, NodeProtocol, NodeResult
from framework.runtime.core import Runtime


DOCUMENT_TEXT_KEY = "document_text"
SUMMARY_KEY = "summary"
ENTITIES_KEY = "entities"


class DocumentIntakeNode(NodeProtocol):
    """
    Node that performs the initial intake of the document text.

    This node is responsible for:
    - Reading the raw document text from the input data.
    - Normalizing whitespace.
    - Persisting the cleaned text into node memory for downstream nodes.
    - Passing the cleaned text forward as part of the node output.
    """

    async def execute(self, ctx: NodeContext) -> NodeResult:
        """
        Execute the intake step.

        Parameters
        ----------
        ctx:
            The `NodeContext` containing input data and shared memory.

        Returns
        -------
        NodeResult
            A successful result with the cleaned document text stored in both
            memory and the node output payload.
        """
        raw_text = str(ctx.input_data.get(DOCUMENT_TEXT_KEY, "")).strip()
        normalized_text = re.sub(r"\s+", " ", raw_text)

        ctx.memory.write(DOCUMENT_TEXT_KEY, normalized_text)

        return NodeResult(
            success=True,
            output={DOCUMENT_TEXT_KEY: normalized_text},
        )


class DocumentExtractionNode(NodeProtocol):
    """
    Node that performs lightweight information extraction over the document text.

    This example uses simple heuristics instead of an LLM:
    - Summary: the first complete sentence, or the first 200 characters.
    - Entities: unique capitalized tokens longer than two characters.
    """

    async def execute(self, ctx: NodeContext) -> NodeResult:
        """
        Execute the extraction step.

        Parameters
        ----------
        ctx:
            The `NodeContext` containing input data and shared memory.

        Returns
        -------
        NodeResult
            A successful result with a structured payload containing:
            - `summary`: short text summary of the document.
            - `entities`: list of main entities detected in the text.
        """
        document_text = str(
            ctx.input_data.get(DOCUMENT_TEXT_KEY)
            or ctx.memory.read(DOCUMENT_TEXT_KEY)
            or ""
        )

        summary = _extract_summary(document_text)
        entities = _extract_entities(document_text)

        ctx.memory.write(SUMMARY_KEY, summary)
        ctx.memory.write(ENTITIES_KEY, entities)

        return NodeResult(
            success=True,
            output={
                SUMMARY_KEY: summary,
                ENTITIES_KEY: entities,
            },
        )


class DocumentOutputNode(NodeProtocol):
    """
    Node that assembles the final structured result for the document.

    This node aggregates:
    - The original (cleaned) document text.
    - The computed summary.
    - The extracted entities.
    """

    async def execute(self, ctx: NodeContext) -> NodeResult:
        """
        Execute the output assembly step.

        Parameters
        ----------
        ctx:
            The `NodeContext` containing input data and shared memory.

        Returns
        -------
        NodeResult
            A successful result with a single `document_analysis` object that
            callers can consume directly.
        """
        document_text = str(
            ctx.input_data.get(DOCUMENT_TEXT_KEY)
            or ctx.memory.read(DOCUMENT_TEXT_KEY)
            or ""
        )
        summary = str(ctx.memory.read(SUMMARY_KEY) or "")
        entities = list(ctx.memory.read(ENTITIES_KEY) or [])

        document_analysis: Dict[str, Any] = {
            DOCUMENT_TEXT_KEY: document_text,
            SUMMARY_KEY: summary,
            ENTITIES_KEY: entities,
        }

        return NodeResult(
            success=True,
            output={"document_analysis": document_analysis},
        )


def _extract_summary(text: str) -> str:
    """
    Create a very lightweight summary from the input text.

    Parameters
    ----------
    text:
        Raw document text to summarize.

    Returns
    -------
    str
        A short summary derived from the first sentence or from the first
        200 characters if no clear sentence boundary is detected.
    """
    if not text:
        return ""

    sentences = re.split(r"(?<=[.!?])\s+", text)
    if sentences and sentences[0]:
        return sentences[0].strip()

    return text[:200].strip()


def _extract_entities(text: str) -> List[str]:
    """
    Extract naive "entities" from the text.

    This function is intentionally simple: it looks for capitalized tokens
    longer than two characters and returns a unique list while preserving
    the original order of appearance.

    Parameters
    ----------
    text:
        Raw document text.

    Returns
    -------
    list[str]
        Ordered list of distinct entity strings.
    """
    if not text:
        return []

    candidates = re.findall(r"\b[A-Z][a-zA-Z]+\b", text)

    seen: set[str] = set()
    entities: List[str] = []
    for token in candidates:
        if token not in seen and len(token) > 2:
            seen.add(token)
            entities.append(token)

    return entities


class DocumentProcessingAgent:
    """
    Minimal document processing agent backed by the Hive graph runtime.

    The agent orchestrates three nodes:
    1. `intake` — normalizes and stores the raw document text.
    2. `extract` — computes a simple summary and naive entities.
    3. `output` — assembles a single structured `document_analysis` payload.
    """

    def __init__(self, storage_path: Path | None = None) -> None:
        """
        Initialize the document processing agent.

        Parameters
        ----------
        storage_path:
            Optional path used by the runtime for logs and internal state.
            When omitted, a default folder under `./agent_logs` is created.
        """
        self.storage_path: Path = storage_path or Path("./agent_logs/document_processing")
        self.storage_path.mkdir(parents=True, exist_ok=True)

        self.goal: Goal = Goal(
            id="document-processing",
            name="Document Processing Agent",
            description=(
                "Extract a short summary and main entities from an input document text "
                "and return a structured analysis object."
            ),
            success_criteria=[
                {
                    "id": "summary-present",
                    "description": "A non-empty summary is produced for non-empty documents.",
                    "metric": "boolean",
                    "target": "true",
                },
                {
                    "id": "entities-detected",
                    "description": "At least one entity is detected when the document contains names.",
                    "metric": "count",
                    "target": ">=0",
                },
            ],
        )

        self.nodes: List[NodeSpec] = [
            NodeSpec(
                id="intake",
                name="Document Intake",
                description="Accept and normalize the raw document text.",
                node_type="event_loop",
                input_keys=[DOCUMENT_TEXT_KEY],
                output_keys=[DOCUMENT_TEXT_KEY],
            ),
            NodeSpec(
                id="extract",
                name="Extraction",
                description="Extract a simple summary and main entities from the document.",
                node_type="event_loop",
                input_keys=[DOCUMENT_TEXT_KEY],
                output_keys=[SUMMARY_KEY, ENTITIES_KEY],
            ),
            NodeSpec(
                id="output",
                name="Output Assembly",
                description="Assemble the final structured document analysis payload.",
                node_type="event_loop",
                input_keys=[SUMMARY_KEY, ENTITIES_KEY, DOCUMENT_TEXT_KEY],
                output_keys=["document_analysis"],
            ),
        ]

        self.edges: List[EdgeSpec] = [
            EdgeSpec(
                id="intake-to-extract",
                source="intake",
                target="extract",
                condition=EdgeCondition.ON_SUCCESS,
            ),
            EdgeSpec(
                id="extract-to-output",
                source="extract",
                target="output",
                condition=EdgeCondition.ON_SUCCESS,
            ),
        ]

        self.entry_node: str = "intake"
        self.terminal_nodes: List[str] = ["output"]

        self.graph: GraphSpec = GraphSpec(
            id="document-processing-graph",
            goal_id=self.goal.id,
            entry_node=self.entry_node,
            terminal_nodes=self.terminal_nodes,
            nodes=self.nodes,
            edges=self.edges,
        )

        self.runtime: Runtime = Runtime(storage_path=self.storage_path)
        self.executor: GraphExecutor = GraphExecutor(runtime=self.runtime)

        self._register_nodes()

    def _register_nodes(self) -> None:
        """
        Register Python node implementations with the graph executor.

        This connects logical node IDs in the graph to the concrete
        `NodeProtocol` implementations defined in this module.
        """
        self.executor.register_node("intake", DocumentIntakeNode())
        self.executor.register_node("extract", DocumentExtractionNode())
        self.executor.register_node("output", DocumentOutputNode())

    async def run(self, document_text: str) -> Dict[str, Any]:
        """
        Execute the document processing agent end-to-end.

        Parameters
        ----------
        document_text:
            Raw content of the document to analyze.

        Returns
        -------
        dict[str, Any]
            A structured analysis object with the following keys:
            - `document_text`: normalized input text.
            - `summary`: lightweight summary string.
            - `entities`: list of detected entities.

        Raises
        ------
        RuntimeError
            If the underlying graph execution fails.
        """
        input_payload: Dict[str, Any] = {DOCUMENT_TEXT_KEY: document_text}

        result: ExecutionResult = await self.executor.execute(
            graph=self.graph,
            goal=self.goal,
            input_data=input_payload,
        )

        if not result.success:
            raise RuntimeError(f"Document processing failed: {result.error}")

        analysis = result.output.get("document_analysis")
        if not isinstance(analysis, dict):
            raise RuntimeError("Document processing did not return a structured analysis.")

        return analysis


async def main() -> None:
    """
    Run a small demonstration of the DocumentProcessingAgent.

    This function builds the agent, feeds it a sample document, and prints the
    resulting structured analysis to stdout.
    """
    agent = DocumentProcessingAgent()

    sample_document = (
        "On 12 March 2026, Acme Corporation finalized a contract with Contoso Bank "
        "for a total amount of 1.2 million dollars. The agreement was signed in "
        "San Francisco and will be effective for three years."
    )

    analysis = await agent.run(sample_document)

    print("=== Document Analysis ===")
    print(f"Summary: {analysis.get(SUMMARY_KEY)}")
    print(f"Entities: {analysis.get(ENTITIES_KEY)}")


if __name__ == "__main__":
    asyncio.run(main())

