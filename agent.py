from langchain_community.chat_models import ChatOllama
from langgraph.graph import StateGraph, END

llm = ChatOllama(model="gemma:2b")

def agent_node(state):
    response = llm.invoke(state["input"])
    return {"output": response.content}

graph = StateGraph(dict)
graph.add_node("agent", agent_node)
graph.set_entry_point("agent")
graph.add_edge("agent", END)

app = graph.compile()

print(app.invoke({"input": "Explain AI agents simply"}))

