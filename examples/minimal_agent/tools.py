from framework.runner.tool_registry import ToolRegistry

def echo(question):
    return {"answer": question}

echo._tool_metadata = {"name": "echo", "description": "Echoes the input question as the answer."}
