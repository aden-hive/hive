from typing import Any, List
from pydantic import BaseModel, Field

class NodePreview(BaseModel):
    """Represents a proposed node in the agent graph."""
    name: str
    node_type: str = Field(description="Type of node: 'llm_generate', 'llm_tool_use', 'router', 'function'")
    purpose: str
    estimated_tools: List[str] = Field(default_factory=list)
    estimated_llm_calls: int = Field(default=1, description="Estimated number of LLM calls")

class EdgePreview(BaseModel):
    """Represents a proposed transition between nodes."""
    source: str
    target: str
    condition_type: str = Field(description="generic, always, on_success, on_failure, conditional, llm_decide")
    routing_summary: str = Field(description="Explanation of when this path is taken")

class RiskFlag(BaseModel):
    """Represents a potential issue or gap in the plan."""
    severity: str = Field(description="'warning' or 'info'")
    message: str
    suggestion: str

class GoalPreview(BaseModel):
    """High-level preview of what the agent will build."""
    goal_summary: str
    proposed_nodes: List[NodePreview]
    proposed_edges: List[EdgePreview]
    estimated_complexity: str = Field(description="'low', 'medium', 'high'")
    estimated_generation_cost: float = Field(description="Estimated USD cost to generate agent")
    estimated_per_run_cost: float = Field(description="Estimated USD cost per execution")
    risk_flags: List[RiskFlag] = Field(default_factory=list)
    suggested_refinements: List[str] = Field(default_factory=list)

import os
import json
from framework.graph.goal import Goal

class PreviewGenerator:
    """Generates a structural preview of an agent from a goal."""
    
    def __init__(self, model: str = "claude-3-haiku-20240307"):
        self.model = model
        # Costs per 1M tokens (approximate for Haiku)
        self.input_cost_per_m = 0.25
        self.output_cost_per_m = 1.25

    async def generate_preview(self, goal: Goal) -> GoalPreview:
        """
        Generate a preview using a single LLM call.
        """
        import os
        import google.generativeai as genai
        
        # Load environment variables if not already loaded
        from dotenv import load_dotenv
        load_dotenv()

        gemini_key = os.environ.get("GEMINI_API_KEY")
        
        system_prompt = """You are an expert AI agent architect. 
Your task is to analyze a user's goal and PREVIEW the agent architecture you would build.
Do NOT build the code. Just outline the structure: nodes, edges, and risks.

Guidelines:
1. Decompose the goal into logical steps (Nodes).
2. Connect them with flow logic (Edges).
3. Identify risks (e.g., missing success criteria, vague requirements).
4. Estimate complexity and cost.

Return valid JSON conforming to this schema:
{
  "goal_summary": "string",
  "proposed_nodes": [
    {
      "name": "string",
      "node_type": "string (llm_generate, llm_tool_use, router, function)",
      "purpose": "string",
      "estimated_tools": ["string"],
      "estimated_llm_calls": int
    }
  ],
  "proposed_edges": [
    {
      "source": "string",
      "target": "string",
      "condition_type": "string (always, on_success, on_failure)",
      "routing_summary": "string"
    }
  ],
  "estimated_complexity": "string (low, medium, high)",
  "estimated_generation_cost": float,
  "estimated_per_run_cost": float
}"""

        user_prompt = f"""Target Goal:
{goal.to_prompt_context()}

Analyze this goal and provide a JSON preview Structure."""

        if gemini_key:
            try:
                genai.configure(api_key=gemini_key)
                # Try with full model path as seen in list_models.py
                model = genai.GenerativeModel('models/gemini-2.5-flash-lite')
                
                response = await model.generate_content_async(
                    f"{system_prompt}\n\n{user_prompt}"
                )
                
                text = response.text
                
                # Extract JSON
                start = text.find('{')
                end = text.rfind('}') + 1
                if start != -1 and end != -1:
                    json_str = text[start:end]
                    data = json.loads(json_str)
                    preview = GoalPreview(**data)
                    
                    # Post-process risks
                    self._enrich_risks(preview, goal)
                    return preview
            except Exception as e:
                import traceback
                print(f"\n[ERROR] Gemini preview generation failed: {e}")
                traceback.print_exc()
                print("Falling back to mock.\n")

        return self._mock_preview(goal) # Fallback

    def _enrich_risks(self, preview: GoalPreview, goal: Goal):
        """Cross-reference goal criteria with nodes to find gaps."""
        # Simple heuristic: if a success criteria keyword isn't in any node purpose, flag it
        node_text = " ".join([n.purpose.lower() for n in preview.proposed_nodes])
        
        for criterion in goal.success_criteria:
            # Check if likely covered
            keywords = [w for w in criterion.description.lower().split() if len(w) > 4]
            # If significant keywords missing
            missing = [k for k in keywords if k not in node_text]
            if len(missing) > len(keywords) * 0.5: # More than half missing
                preview.risk_flags.append(RiskFlag(
                    severity="warning",
                    message=f"Critierion '{criterion.description}' may not be covered.",
                    suggestion="Add a specific verification step."
                ))

    def _mock_preview(self, goal: Goal) -> GoalPreview:
        """Fallback mock for testing or offline mode."""
        return GoalPreview(
            goal_summary=f"Preview for: {goal.name}",
            proposed_nodes=[
                NodePreview(name="InputProcessor", node_type="function", purpose="Parse input"),
                NodePreview(name="MainLogic", node_type="llm_generate", purpose="Execute core task"),
                NodePreview(name="OutputFormatter", node_type="function", purpose="Format result")
            ],
            proposed_edges=[
                EdgePreview(source="InputProcessor", target="MainLogic", condition_type="always", routing_summary="Always proceed"),
                EdgePreview(source="MainLogic", target="OutputFormatter", condition_type="on_success", routing_summary="If logic succeeds")
            ],
            estimated_complexity="medium",
            estimated_generation_cost=0.05,
            estimated_per_run_cost=0.01,
            risk_flags=[
                RiskFlag(severity="info", message="Mock preview generated.", suggestion="Check API keys.")
            ]
        )
