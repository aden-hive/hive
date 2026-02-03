"""
Example usage of the Agent Versioning & Rollback System

This demonstrates how to:
1. Save agent versions
2. Load and rollback versions
3. Compare versions
4. Use tags
5. Set up A/B testing
"""

import asyncio
from pathlib import Path

from framework.graph import Goal
from framework.graph.edge import GraphSpec
from framework.graph.goal import Constraint, SuccessCriterion
from framework.graph.node import NodeSpec
from framework.runner import AgentRunner
from framework.runner.ab_testing import create_ab_test_session
from framework.runner.versioning import AgentVersionManager
from framework.schemas.version import BumpType


def create_sample_agent_v1():
    """Create a simple agent (version 1)"""
    goal = Goal(
        id="email-agent",
        name="Email Assistant",
        description="Helps draft and send emails",
        success_criteria=[
            SuccessCriterion(
                id="complete",
                description="Email successfully drafted",
                metric="success",
                target="true",
                weight=1.0,
            )
        ],
        constraints=[
            Constraint(
                id="no-errors",
                description="No errors in processing",
                constraint_type="hard",
                category="safety",
                check="error == null",
            )
        ],
    )

    graph = GraphSpec(
        id="email-graph-v1",
        goal_id="email-agent",
        entry_node="start",
        terminal_nodes=["end"],
        nodes=[
            NodeSpec(
                id="start",
                node_type="input",
                name="Start",
                description="Receive email request",
                input_keys=["subject", "recipient"],
                output_keys=["email_data"],
            ),
            NodeSpec(
                id="draft",
                node_type="llm",
                name="Draft Email",
                description="Generate email content",
                input_keys=["email_data"],
                output_keys=["draft"],
            ),
            NodeSpec(
                id="end",
                node_type="output",
                name="End",
                description="Return result",
                input_keys=["draft"],
                output_keys=["result"],
            ),
        ],
        edges=[],
    )

    return graph, goal


def create_sample_agent_v2():
    """Create an improved agent (version 2) with validation."""
    goal = Goal(
        id="email-agent",
        name="Email Assistant",
        description="Helps draft and send emails with validation",
        success_criteria=[
            SuccessCriterion(
                id="complete",
                description="Email successfully drafted and validated",
                metric="success",
                target="true",
                weight=1.0,
            )
        ],
        constraints=[
            Constraint(
                id="no-errors",
                description="No errors in processing",
                constraint_type="hard",
                category="safety",
                check="error == null",
            )
        ],
    )

    graph = GraphSpec(
        id="email-graph-v2",
        goal_id="email-agent",
        entry_node="start",
        terminal_nodes=["end"],
        nodes=[
            NodeSpec(
                id="start",
                node_type="input",
                name="Start",
                description="Receive email request",
                input_keys=["subject", "recipient"],
                output_keys=["email_data"],
            ),
            NodeSpec(
                id="validate",
                node_type="function",
                name="Validate Input",
                description="Validate email addresses",
                input_keys=["email_data"],
                output_keys=["validated_data"],
            ),
            NodeSpec(
                id="draft",
                node_type="llm",
                name="Draft Email",
                description="Generate email content",
                input_keys=["validated_data"],
                output_keys=["draft"],
            ),
            NodeSpec(
                id="end",
                node_type="output",
                name="End",
                description="Return result",
                input_keys=["draft"],
                output_keys=["result"],
            ),
        ],
        edges=[],
    )

    return graph, goal


def demo_basic_versioning():
    """Demonstrate basic versioning operations"""

    versions_dir = Path(".demo_versions")
    manager = AgentVersionManager(versions_dir)

    # Create and save version 1.0.0
    print("\n1. Saving initial version (1.0.0)...")
    graph_v1, goal_v1 = create_sample_agent_v1()
    version1 = manager.save_version(
        agent_id="email-agent",
        graph=graph_v1,
        goal=goal_v1,
        description="Initial release with basic email drafting",
        bump=BumpType.PATCH,
        created_by="alice@example.com",
    )
    print(f"   Saved version {version1.version}")

    # Create and save version 1.1.0
    print("\n2. Saving enhanced version (1.1.0)...")
    graph_v2, goal_v2 = create_sample_agent_v2()
    version2 = manager.save_version(
        agent_id="email-agent",
        graph=graph_v2,
        goal=goal_v2,
        description="Added email address validation",
        bump=BumpType.MINOR,
        created_by="bob@example.com",
    )
    print(f"   Saved version {version2.version}")


    print("\n3. Listing all versions...")
    versions = manager.list_versions("email-agent")
    for v in versions:
        print(f"   - {v.version}: {v.description}")

    print("\n4. Comparing versions 1.0.0 vs 1.1.0...")
    diff = manager.compare_versions("email-agent", "1.0.0", "1.1.0")
    print(f"   Summary: {diff.summary}")
    if diff.nodes_added:
        print(f"   Nodes added: {', '.join(diff.nodes_added)}")

    # Tag the stable version
    print("\n5. Tagging version 1.0.0 as 'stable'...")
    manager.tag_version("email-agent", "1.0.0", "stable")
    print("   Tagged successfully")

    # Rollback to previous version
    print("\n6. Rolling back to version 1.0.0...")
    graph, goal = manager.rollback("email-agent", "1.0.0")
    print(f"   Rolled back to version {graph.id}")

    # Verify current version
    registry = manager._load_registry("email-agent")
    print(f"   Current version: {registry.current_version}")

    print("\n Basic versioning demo complete!\n")


def demo_ab_testing():
    """Demonstrate A/B testing functionality"""

    versions_dir = Path(".demo_versions")
    manager = AgentVersionManager(versions_dir)

    # Ensure we have two versions
    registry = manager._load_registry("email-agent")
    if len(registry.versions) < 2:
        print("Error: Need at least 2 versions. Run basic versioning demo first.")
        return

    # Create A/B test
    print("\n1. Creating A/B test between versions 1.0.0 and 1.1.0...")
    router = create_ab_test_session(
        agent_id="email-agent",
        version_a="1.0.0",
        version_b="1.1.0",
        traffic_split=0.5,
        metrics=["response_time", "success_rate"],
        versions_dir=versions_dir,
    )
    print("   A/B test created")

    # Simulate some requests
    print("\n2. Simulating 10 requests...")
    for i in range(10):
        request_id = f"request-{i}"
        version = router.route(request_id)

        import random

        if version == "1.0.0":
            response_time = random.uniform(0.5, 1.0)
            success_rate = random.uniform(0.8, 0.9)
        else:
            response_time = random.uniform(0.6, 1.1)
            success_rate = random.uniform(0.9, 0.95)

        router.record_execution(
            request_id=request_id,
            version=version,
            metrics={"response_time": response_time, "success_rate": success_rate},
        )

        print(f"   Request {i+1}: routed to {version}")

    print("\n3. Analyzing A/B test results...")
    results = router.get_results()
    print(f"   Version A (1.0.0): {results.executions_a} executions")
    print(f"   Version B (1.1.0): {results.executions_b} executions")

    if results.metrics_a:
        print(f"\n   Metrics for Version A:")
        for metric, value in results.metrics_a.items():
            print(f"     {metric}: {value:.3f}")

    if results.metrics_b:
        print(f"\n   Metrics for Version B:")
        for metric, value in results.metrics_b.items():
            print(f"     {metric}: {value:.3f}")

    # Analyze and determine winner
    analysis = router.analyze_results(primary_metric="success_rate")
    print(f"\n4. Winner: {analysis.get('winner', 'Not determined')}")
    print(f"   Confidence: {analysis.get('confidence', 'N/A')}")

    router.end_test(winner=analysis.get("winner"), notes="Higher success rate in version B")
    print("\n A/B testing demo complete!\n")


def main():
    """Run all demos"""
    print("\n")
    print("Agent Versioning System Demo")

    print()

    try:
        # Run demos
        demo_basic_versioning()

        demo_ab_testing()


        print()
        print("Check the following files:")
        print("  - .demo_versions/email-agent/registry.json")
        print("  - .demo_versions/email-agent/versions/*.json")
        print("  - .demo_versions/email-agent/ab_tests/*.json")
        print()

    except Exception as e:
        print(f"\n Error during demo: {e}")
        import traceback

        traceback.print_exc()


if __name__ == "__main__":
    main()
