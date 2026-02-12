"""
CLI tool for trace debugging and analysis.

Provides commands for:
- Indexing agent execution traces
- Building vector index for semantic search
- Querying traces with natural language
- Analyzing patterns (failures, performance, etc.)

Usage:
    python -m framework.debugging.cli index <agent_path>
    python -m framework.debugging.cli build-vector-index <agent_path>
    python -m framework.debugging.cli query <agent_path> "find failed runs"
    python -m framework.debugging.cli analyze <agent_path> --pattern failures
"""

import asyncio
from pathlib import Path
from typing import Literal

import click

from framework.debugging.index_store import IndexStore
from framework.debugging.trace_embedder import TraceEmbedder
from framework.debugging.trace_indexer import TraceIndexer
from framework.debugging.trace_rag import TraceRAG
from framework.debugging.trace_vector_store import TraceVectorStore


@click.group()
def cli():
    """Hive Trace Debugger - Analyze agent execution traces."""
    pass


@cli.command()
@click.argument("agent_path", type=click.Path(exists=True, path_type=Path))
def index(agent_path: Path):
    """Index all traces from agent sessions.

    Scans session directories, reads L1/L2/L3 logs, and builds searchable index.

    Example:
        python -m framework.debugging.cli index ~/.hive/agents/sales_agent
    """

    async def _index():
        click.echo(f"Indexing traces from: {agent_path}")

        indexer = TraceIndexer(agent_path)
        store = IndexStore(base_path=agent_path)

        # Load existing index
        await store.load()
        click.echo(f"Existing index: {len(store.index)} traces")

        # Index all sessions
        stats = await indexer.index_all_sessions(store)

        # Save updated index
        await store.save()

        click.echo("\n✓ Indexing complete!")
        click.echo(f"  Indexed: {stats['indexed']}")
        click.echo(f"  Skipped: {stats['skipped']}")
        click.echo(f"  Errors: {stats['errors']}")
        click.echo(f"  Total traces: {len(store.index)}")

    asyncio.run(_index())


@cli.command()
@click.argument("agent_path", type=click.Path(exists=True, path_type=Path))
@click.option("--dimension", default=384, help="Embedding dimension")
def build_vector_index(agent_path: Path, dimension: int):
    """Build vector index for semantic search.

    Reads trace index, generates embeddings, and builds FAISS index.

    Example:
        python -m framework.debugging.cli build-vector-index ~/.hive/agents/sales_agent
    """

    async def _build():
        click.echo(f"Building vector index for: {agent_path}")

        # Load trace index
        store = IndexStore(base_path=agent_path)
        await store.load()

        traces = store.list_all()
        if not traces:
            click.echo("✗ No traces found. Run 'index' command first.")
            return

        click.echo(f"Found {len(traces)} traces")

        # Initialize embedder and vector store
        click.echo("Initializing embedder (downloading model if needed)...")
        embedder = TraceEmbedder()

        vector_store = TraceVectorStore(
            storage_path=agent_path / ".vector_index", dimension=dimension
        )
        await vector_store.initialize()

        # Generate embeddings in batches
        click.echo("Generating embeddings...")
        with click.progressbar(length=len(traces)) as bar:
            batch_size = 10
            for i in range(0, len(traces), batch_size):
                batch = traces[i : i + batch_size]
                embeddings = await embedder.embed_traces(batch)
                await vector_store.add_traces(batch, embeddings)
                bar.update(len(batch))

        # Save vector index
        click.echo("Saving vector index...")
        await vector_store.save()

        click.echo(f"\n✓ Vector index built: {vector_store.size()} traces")

    asyncio.run(_build())


@cli.command()
@click.argument("agent_path", type=click.Path(exists=True, path_type=Path))
@click.argument("question")
@click.option("--k", default=5, help="Number of traces to retrieve")
@click.option("--no-context", is_flag=True, help="Hide retrieved traces")
@click.option(
    "--provider",
    type=click.Choice(["openai", "anthropic", "google"]),
    help="LLM provider (auto-detects if not specified)",
)
@click.option("--model", help="Model name (uses provider default if not specified)")
def query(
    agent_path: Path,
    question: str,
    k: int,
    no_context: bool,
    provider: str | None,
    model: str | None,
):
    """Query traces using natural language.

    Uses RAG (Retrieval-Augmented Generation) to answer questions about traces.
    Supports OpenAI, Anthropic (Claude), and Google (Gemini) via LangChain.

    Environment Variables:
        HIVE_LLM_PROVIDER: Default provider (openai|anthropic|google)
        OPENAI_API_KEY, ANTHROPIC_API_KEY, GOOGLE_API_KEY: API keys

    Examples:
        python -m framework.debugging.cli query ~/.hive/agents/sales_agent "Why?"
        python -m framework.debugging.cli query ... --provider openai
        python -m framework.debugging.cli query ... --provider anthropic --model claude-3-opus
        python -m framework.debugging.cli query ... --provider google --model gemini-1.5-pro
    """

    async def _query():
        # Check if vector index exists
        vector_path = agent_path / ".vector_index"
        if not vector_path.exists():
            click.echo("✗ Vector index not found. Run 'build-vector-index' first.")
            return

        # Initialize components
        embedder = TraceEmbedder()
        vector_store = TraceVectorStore(storage_path=vector_path)
        await vector_store.initialize()

        if vector_store.size() == 0:
            click.echo("✗ Vector index is empty. Run 'build-vector-index' first.")
            return

        # Create RAG engine with provider
        try:
            rag = TraceRAG(embedder, vector_store, provider=provider, model=model)  # type: ignore
        except (ValueError, ImportError) as e:
            click.echo(f"✗ LLM initialization failed: {e}")
            return

        # Query
        click.echo(f"Querying: {question}\n")
        result = await rag.query(question, k=k, include_context=not no_context)

        # Display answer
        click.echo("Answer:")
        click.echo("-" * 80)
        click.echo(result["answer"])
        click.echo("-" * 80)

        # Display retrieved traces if requested
        if not no_context and "traces" in result:
            click.echo(f"\nRetrieved Traces ({len(result['traces'])}):")
            for i, trace in enumerate(result["traces"], 1):
                click.echo(f"\n{i}. {trace.run_id}")
                click.echo(f"   Status: {trace.status}")
                click.echo(f"   Agent: {trace.agent_id}")
                click.echo(f"   Latency: {trace.total_latency_ms}ms")
                click.echo(f"   Tokens: {trace.total_tokens}")
                if trace.error_message:
                    click.echo(f"   Error: {trace.error_message}")

    asyncio.run(_query())


@cli.command()
@click.argument("agent_path", type=click.Path(exists=True, path_type=Path))
@click.option(
    "--pattern",
    type=click.Choice(["failures", "performance", "retry_patterns", "error_clusters"]),
    required=True,
    help="Pattern type to analyze",
)
@click.option("--limit", default=10, help="Number of traces to analyze")
@click.option(
    "--provider",
    type=click.Choice(["openai", "anthropic", "google"]),
    help="LLM provider (auto-detects if not specified)",
)
@click.option("--model", help="Model name (uses provider default if not specified)")
def analyze(
    agent_path: Path,
    pattern: Literal["failures", "performance", "retry_patterns", "error_clusters"],
    limit: int,
    provider: str | None,
    model: str | None,
):
    """Analyze patterns across traces.

    Supports OpenAI, Anthropic (Claude), and Google (Gemini) via LangChain.

    Environment Variables:
        HIVE_LLM_PROVIDER: Default provider (openai|anthropic|google)
        OPENAI_API_KEY, ANTHROPIC_API_KEY, GOOGLE_API_KEY: API keys

    Examples:
        python -m framework.debugging.cli analyze ~/.hive/agents/sales_agent --pattern failures
        python -m framework.debugging.cli analyze ... --pattern failures --provider openai
        python -m framework.debugging.cli analyze ... --pattern performance --provider google
    """

    async def _analyze():
        # Check if vector index exists
        vector_path = agent_path / ".vector_index"
        if not vector_path.exists():
            click.echo("✗ Vector index not found. Run 'build-vector-index' first.")
            return

        # Initialize components
        embedder = TraceEmbedder()
        vector_store = TraceVectorStore(storage_path=vector_path)
        await vector_store.initialize()

        if vector_store.size() == 0:
            click.echo("✗ Vector index is empty.")
            return

        # Create RAG engine with provider
        try:
            rag = TraceRAG(embedder, vector_store, provider=provider, model=model)  # type: ignore
        except (ValueError, ImportError) as e:
            click.echo(f"✗ LLM initialization failed: {e}")
            return

        # Analyze pattern
        click.echo(f"Analyzing {pattern} patterns (limit={limit})...\n")
        analysis = await rag.analyze_pattern(pattern, limit=limit)

        # Display analysis
        click.echo("Analysis:")
        click.echo("=" * 80)
        click.echo(analysis)
        click.echo("=" * 80)

    asyncio.run(_analyze())


@cli.command()
@click.argument("agent_path", type=click.Path(exists=True, path_type=Path))
def stats(agent_path: Path):
    """Show statistics about indexed traces.

    Example:
        python -m framework.debugging.cli stats ~/.hive/agents/sales_agent
    """

    async def _stats():
        # Load trace index
        store = IndexStore(base_path=agent_path)
        await store.load()

        traces = store.list_all()

        if not traces:
            click.echo("No traces found.")
            return

        # Calculate statistics
        total = len(traces)
        success = sum(1 for t in traces if t.status == "success")
        failure = sum(1 for t in traces if t.status == "failure")
        degraded = sum(1 for t in traces if t.status == "degraded")

        avg_latency = sum(t.total_latency_ms for t in traces) / total
        avg_tokens = sum(t.total_tokens for t in traces) / total

        # Display statistics
        click.echo(f"Trace Statistics for: {agent_path}")
        click.echo("=" * 80)
        click.echo(f"Total Traces: {total}")
        click.echo(f"  Success: {success} ({success / total * 100:.1f}%)")
        click.echo(f"  Failure: {failure} ({failure / total * 100:.1f}%)")
        click.echo(f"  Degraded: {degraded} ({degraded / total * 100:.1f}%)")
        click.echo(f"\nAverage Latency: {avg_latency:.0f}ms")
        click.echo(f"Average Tokens: {avg_tokens:.0f}")

        # Most common errors
        errors = [t.error_message for t in traces if t.error_message]
        if errors:
            click.echo("\nMost Common Errors:")
            from collections import Counter

            for error, count in Counter(errors).most_common(5):
                click.echo(f"  {count}x: {error[:60]}...")

        # Check vector index
        vector_path = agent_path / ".vector_index"
        if vector_path.exists():
            vector_store = TraceVectorStore(storage_path=vector_path)
            await vector_store.initialize()
            click.echo(f"\nVector Index: {vector_store.size()} traces indexed")
        else:
            click.echo("\nVector Index: Not built")

    asyncio.run(_stats())


if __name__ == "__main__":
    cli()
