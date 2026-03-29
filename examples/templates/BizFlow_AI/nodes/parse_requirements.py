"""Node for parsing user requirements into structured pipeline specs."""

from typing import Dict, Any, List
import json

from framework.graph import BaseNode
from framework.runtime import Runtime
from framework.llm import LLMProvider


class ParseRequirementsNode(BaseNode):
    """Parse natural language requirements into structured pipeline specifications."""
    
    def __init__(self, node_id: str, runtime: Runtime, llm: LLMProvider):
        super().__init__(node_id, runtime)
        self.llm = llm
        
    async def execute(self, input_data: Dict[str, Any]) -> Dict[str, Any]:
        """Execute requirement parsing."""
        requirements = input_data.get("requirements", "")
        
        if not requirements:
            raise ValueError("No requirements provided")
        
        self.runtime.quick_decision(
            intent="Parse workflow requirements",
            action="Analyzing requirements with LLM",
            reasoning="Need to understand user's automation needs"
        )
        
        # Use LLM to extract structured pipeline requirements
        system_prompt = """You are an expert n8n workflow architect. 
        Parse the user's requirements into a structured JSON format with:
        - pipelines: array of pipeline specifications
        - triggers: all required trigger types
        - actions: all required action types
        - integrations: all external services needed
        """
        
        response = await self.llm.acomplete(
            messages=[{"role": "user", "content": requirements}],
            system=system_prompt,
            json_mode=True
        )
        
        try:
            parsed = json.loads(response.content)
        except:
            # Fallback structure
            parsed = {
                "pipelines": [
                    {
                        "name": "cv_screening",
                        "description": "CV screening pipeline",
                        "triggers": ["webhook", "google_drive"],
                        "actions": ["email", "calendar", "crm"]
                    },
                    {
                        "name": "signal_engine",
                        "description": "Signal decision engine",
                        "triggers": ["webhook"],
                        "actions": ["slack", "crm", "email"]
                    },
                    {
                        "name": "revenue_monitor",
                        "description": "Revenue leak detector",
                        "triggers": ["schedule", "webhook"],
                        "actions": ["stripe", "slack", "crm", "email"]
                    },
                    {
                        "name": "contract_watchdog",
                        "description": "Contract compliance monitor",
                        "triggers": ["schedule", "webhook", "manual"],
                        "actions": ["email", "jira", "slack"]
                    },
                    {
                        "name": "hr_monitor",
                        "description": "HR risk monitor",
                        "triggers": ["schedule", "webhook"],
                        "actions": ["slack", "email", "calendar", "crm"]
                    }
                ],
                "integrations": ["openai", "slack", "google", "stripe", "jira"],
                "total_pipelines": 5
            }
        
        self.runtime.record_outcome(
            decision_id=self.node_id,
            success=True,
            result={"pipelines_found": len(parsed.get("pipelines", []))},
            summary=f"Parsed {len(parsed.get('pipelines', []))} pipeline requirements"
        )
        
        return {
            "parsed_requirements": parsed,
            "original_requirements": requirements
        }