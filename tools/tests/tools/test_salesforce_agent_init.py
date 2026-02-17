
import asyncio
from exports.salesforce_manager.agent import SalesforceManagerAgent

async def validate_agent():
    agent = SalesforceManagerAgent()
    # Simple check for nodes and edges
    print(f"Agent Name: {agent.goal.name}")
    print(f"Nodes: {[n.id for n in agent.nodes]}")
    print(f"Edges: {[e.id for e in agent.edges]}")
    
    # Check if we can start it (mock mode)
    await agent.start(mock_mode=True)
    print("Agent started successfully (mock mode).")
    await agent.stop()

if __name__ == "__main__":
    asyncio.run(validate_agent())
