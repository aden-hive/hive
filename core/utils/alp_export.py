import json


def export_agent_alp(agent):
    return {
        "alp_version": "0.3.0",
        "agent_id": getattr(agent, "id", "unknown"),
        "capabilities": ["tool-use"],
        "tools": [
            tool if isinstance(tool, str) else getattr(tool, "name", str(tool))
            for tool in getattr(agent, "tools", [])
        ],
        "llm": getattr(agent, "llm", "unknown"),
    }


def save_alp(agent, output_path="agent.alp.json"):
    data = export_agent_alp(agent)
    with open(output_path, "w") as f:
        json.dump(data, f, indent=2)
