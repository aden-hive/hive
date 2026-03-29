"""Node for validating the generated n8n workflow."""

from typing import Dict, Any
import json

from framework.graph import BaseNode
from framework.runtime import Runtime
from framework.llm import LLMProvider


class ValidateWorkflowNode(BaseNode):
    """Validate the generated n8n workflow for correctness."""
    
    def __init__(self, node_id: str, runtime: Runtime, llm: LLMProvider):
        super().__init__(node_id, runtime)
        self.llm = llm
        
    async def execute(self, input_data: Dict[str, Any]) -> Dict[str, Any]:
        """Execute workflow validation."""
        merged_workflow = input_data.get("merged_workflow", {})
        
        self.runtime.quick_decision(
            intent="Validate workflow",
            action="Checking workflow for errors and completeness",
            reasoning="Ensure generated workflow is production-ready"
        )
        
        # Basic validation checks
        validation_results = {
            "valid": True,
            "warnings": [],
            "errors": [],
            "recommendations": []
        }
        
        # Check for required nodes
        nodes = merged_workflow.get("nodes", [])
        if not nodes:
            validation_results["errors"].append("No nodes in workflow")
            validation_results["valid"] = False
        
        # Check for OpenAI nodes
        openai_nodes = [n for n in nodes if "openAi" in n.get("type", "")]
        if len(openai_nodes) < 5:  # Should have at least 5 AI nodes
            validation_results["warnings"].append(f"Expected at least 5 AI nodes, found {len(openai_nodes)}")
        
        # Check for trigger nodes
        triggers = [n for n in nodes if "Trigger" in n.get("type", "")]
        if len(triggers) < 5:  # Should have multiple triggers
            validation_results["warnings"].append(f"Expected multiple triggers, found {len(triggers)}")
        
        # Check connections
        connections = merged_workflow.get("connections", {})
        connected_nodes = set()
        for source, targets in connections.items():
            connected_nodes.add(source)
            for target_list in targets.values():
                for target in target_list:
                    connected_nodes.add(target["node"])
        
        # Warn about disconnected nodes
        node_names = {n["name"] for n in nodes}
        disconnected = node_names - connected_nodes
        if disconnected:
            validation_results["warnings"].append(f"Disconnected nodes: {', '.join(disconnected)}")
        
        # Use LLM for advanced validation
        validation_prompt = f"""Validate this n8n workflow JSON and provide recommendations:
        
        Workflow: {json.dumps(merged_workflow, indent=2)[:2000]}...
        
        Check for:
        1. Missing placeholder values
        2. Proper node connections
        3. Error handling
        4. Production readiness
        
        Return JSON with:
        - valid: boolean
        - issues: array of issues found
        - recommendations: array of improvements
        """
        
        try:
            llm_response = await self.llm.acomplete(
                messages=[{"role": "user", "content": validation_prompt}],
                system="You are an n8n workflow validation expert.",
                json_mode=True
            )
            
            llm_results = json.loads(llm_response.content)
            validation_results["llm_validation"] = llm_results
            
        except Exception as e:
            validation_results["warnings"].append(f"LLM validation failed: {str(e)}")
        
        self.runtime.record_outcome(
            decision_id=self.node_id,
            success=validation_results["valid"],
            result={
                "valid": validation_results["valid"],
                "warnings": len(validation_results["warnings"]),
                "errors": len(validation_results["errors"])
            },
            summary=f"Workflow validation {'passed' if validation_results['valid'] else 'failed'}"
        )
        
        return {
            "validation_results": validation_results,
            "workflow": merged_workflow
        }