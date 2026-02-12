"""
TraceRAG: Retrieval-Augmented Generation for trace analysis.

Combines semantic search with LLM to provide intelligent insights
about agent execution traces.

Follows Hive patterns:
- Async I/O
- Type safety with Pydantic
- LangChain integration
- Non-fatal error handling

Reference: LangChain RAG documentation
"""

import logging
from typing import Literal

from langchain_core.language_models.chat_models import BaseChatModel
from langchain_core.messages import HumanMessage, SystemMessage

from framework.debugging.llm_provider import LLMProvider, create_llm
from framework.debugging.trace_embedder import TraceEmbedder
from framework.debugging.trace_index import TraceIndex
from framework.debugging.trace_vector_store import TraceVectorStore

logger = logging.getLogger(__name__)


class TraceRAG:
    """
    Retrieval-Augmented Generation for trace analysis.

    Combines semantic search with LLM to answer questions about
    agent execution traces, identify patterns, and provide insights.

    Follows Hive patterns:
    - Async I/O
    - Type safety
    - Non-fatal error handling
    """

    def __init__(
        self,
        embedder: TraceEmbedder,
        vector_store: TraceVectorStore,
        llm: BaseChatModel | None = None,
        provider: LLMProvider | None = None,
        model: str | None = None,
        api_key: str | None = None,
    ):
        """
        Initialize RAG query engine with multi-provider LLM support.

        Args:
            embedder: TraceEmbedder for generating query embeddings
            vector_store: TraceVectorStore for semantic search
            llm: Pre-configured LangChain chat model. If None, creates via provider factory.
            provider: LLM provider ("openai", "anthropic", "google"). Auto-detects if None.
            model: Model name (uses provider default if None)
            api_key: API key (uses environment variable if None)

        Environment Variables:
            HIVE_LLM_PROVIDER: Default provider (openai|anthropic|google)
            OPENAI_API_KEY: OpenAI API key
            ANTHROPIC_API_KEY: Anthropic API key
            GOOGLE_API_KEY: Google API key

        Example:
            # Auto-detect provider
            rag = TraceRAG(embedder, vector_store)

            # Explicit provider
            rag = TraceRAG(embedder, vector_store, provider="openai", model="gpt-4")
            rag = TraceRAG(embedder, vector_store, provider="anthropic")
            rag = TraceRAG(embedder, vector_store, provider="google", model="gemini-1.5-pro")
        """
        self.embedder = embedder
        self.vector_store = vector_store

        # Initialize LLM via provider factory
        if llm is None:
            self.llm = create_llm(
                provider=provider,
                model=model,
                api_key=api_key,
                temperature=0.0,  # Deterministic for analysis
            )
        else:
            self.llm = llm

    async def query(
        self, question: str, k: int = 5, include_context: bool = True
    ) -> dict[str, str | list[TraceIndex]]:
        """
        Answer a question about traces using RAG.

        Steps:
        1. Generate embedding for the question
        2. Retrieve similar traces from vector store
        3. Format context from retrieved traces
        4. Generate answer using LLM

        Args:
            question: User question about traces
            k: Number of traces to retrieve
            include_context: Whether to include retrieved traces in response

        Returns:
            dict with 'answer' (str) and optionally 'traces' (list[TraceIndex])
        """
        # Step 1: Generate query embedding
        logger.debug("Generating embedding for query: %s", question)
        query_embedding = await self.embedder.embed_query(question)

        # Step 2: Retrieve similar traces
        logger.debug("Searching for %d similar traces", k)
        results = await self.vector_store.search(query_embedding, k=k)

        if not results:
            return {"answer": "No traces found. The index may be empty.", "traces": []}

        traces = [trace for trace, _ in results]

        # Step 3: Format context
        context = self._format_context(traces)

        # Step 4: Generate answer
        logger.debug("Generating answer using LLM")
        answer = await self._generate_answer(question, context)

        response = {"answer": answer}
        if include_context:
            response["traces"] = traces

        return response

    async def analyze_pattern(
        self,
        pattern_type: Literal["failures", "performance", "retry_patterns", "error_clusters"],
        limit: int = 10,
    ) -> str:
        """
        Analyze patterns across traces.

        Args:
            pattern_type: Type of pattern to analyze
            limit: Maximum number of traces to analyze

        Returns:
            Analysis summary
        """
        # Build query based on pattern type
        queries = {
            "failures": "agent runs that failed with errors",
            "performance": "agent runs with high latency or token usage",
            "retry_patterns": "agent runs with high retry counts",
            "error_clusters": "common error messages across runs",
        }

        query = queries.get(pattern_type, "all agent runs")
        result = await self.query(query, k=limit, include_context=True)

        # Generate pattern analysis
        traces = result.get("traces", [])
        if not traces:
            return "No traces found for pattern analysis."

        context = self._format_context(traces)
        analysis_prompt = (
            f"Analyze the following traces to identify {pattern_type}. "
            f"Provide insights, common patterns, and recommendations.\n\n"
            f"{context}"
        )

        return await self._generate_answer(analysis_prompt, context)

    def _format_context(self, traces: list[TraceIndex]) -> str:
        """
        Format retrieved traces as context for LLM.

        Args:
            traces: List of retrieved traces

        Returns:
            Formatted context string
        """
        context_parts = ["Retrieved Traces:\n"]

        for i, trace in enumerate(traces, 1):
            context_parts.append(f"\n--- Trace {i} ---")
            context_parts.append(f"Run ID: {trace.run_id}")
            context_parts.append(f"Agent: {trace.agent_id}")
            context_parts.append(f"Status: {trace.status}")
            context_parts.append(f"Quality: {trace.execution_quality}")
            context_parts.append(f"Latency: {trace.total_latency_ms}ms")
            context_parts.append(f"Tokens: {trace.total_tokens}")
            context_parts.append(f"Nodes: {trace.node_count}")

            if trace.node_ids:
                context_parts.append(f"Execution Path: {' -> '.join(trace.node_ids)}")

            if trace.error_message:
                context_parts.append(f"Error: {trace.error_message}")
                if trace.failed_node_id:
                    context_parts.append(f"Failed Node: {trace.failed_node_id}")

        return "\n".join(context_parts)

    async def _generate_answer(self, question: str, context: str) -> str:
        """
        Generate answer using LLM with retrieved context.

        Args:
            question: User question
            context: Retrieved trace context

        Returns:
            LLM-generated answer
        """
        system_prompt = """You are a debugging assistant analyzing Hive agent execution traces.
Your role is to:
- Identify patterns in failures, performance issues, and retry loops
- Provide actionable insights for debugging
- Suggest root causes and solutions
- Be concise and specific

Use the retrieved trace data to answer questions accurately."""

        messages = [
            SystemMessage(content=system_prompt),
            HumanMessage(content=f"Context:\n{context}\n\nQuestion: {question}"),
        ]

        try:
            response = await self.llm.ainvoke(messages)
            return response.content
        except Exception:
            logger.exception("Failed to generate answer using LLM")
            return "Error: Failed to generate answer. Please check your API key and try again."

    async def find_similar_failures(
        self, trace: TraceIndex, k: int = 5
    ) -> list[tuple[TraceIndex, float]]:
        """
        Find traces with similar failures.

        Args:
            trace: Reference trace to find similar failures for
            k: Number of similar traces to return

        Returns:
            List of (TraceIndex, distance) tuples
        """
        # Generate embedding for the reference trace
        embedding = await self.embedder.embed_trace(trace)

        # Search for similar traces
        results = await self.vector_store.search(embedding, k=k + 1)

        # Filter out the reference trace itself and failed traces only
        similar_failures = [
            (t, dist)
            for t, dist in results
            if t.run_id != trace.run_id and t.status in ["failure", "degraded"]
        ]

        return similar_failures[:k]
