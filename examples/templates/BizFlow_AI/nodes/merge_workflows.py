"""Node for merging individual pipeline workflows into a single workflow."""

from typing import Dict, Any, List
import json

from framework.graph import BaseNode
from framework.runtime import Runtime


class MergeWorkflowsNode(BaseNode):
    """Merge individual pipeline workflows into a complete n8n workflow."""
    
    def __init__(self, node_id: str, runtime: Runtime):
        super().__init__(node_id, runtime)
        
    async def execute(self, input_data: Dict[str, Any]) -> Dict[str, Any]:
        """Execute workflow merging."""
        # Collect all pipeline workflows
        pipelines = []
        for key, value in input_data.items():
            if key.startswith("pipeline_") and isinstance(value, dict):
                pipelines.append(value)
        
        self.runtime.quick_decision(
            intent="Merge pipeline workflows",
            action=f"Merging {len(pipelines)} pipelines",
            reasoning="Create complete n8n workflow"
        )
        
        # Start with base workflow structure
        merged = {
            "name": "Multi-Pipeline Business Automation",
            "nodes": [],
            "connections": {}
        }
        
        # Add all nodes from each pipeline
        node_offset = 0
        for i, pipeline in enumerate(pipelines):
            workflow = pipeline.get("workflow", {})
            nodes = workflow.get("nodes", [])
            
            # Adjust node positions to separate pipelines vertically
            for node in nodes:
                if "position" in node:
                    node["position"][1] += i * 800  # Space pipelines vertically
                merged["nodes"].append(node)
            
            # Merge connections with adjusted node names
            for source, targets in workflow.get("connections", {}).items():
                merged["connections"][source] = targets
            
            node_offset += len(nodes)
        
        # Add placeholder values
        merged["placeholder_values"] = {
            "slack": {
                "slackChannel": "YOUR_SLACK_CHANNEL_ID",
                "slackWebhookUrl": "YOUR_SLACK_WEBHOOK_URL"
            },
            "email": {
                "fromEmail": "noreply@yourcompany.com",
                "smtpHost": "smtp.gmail.com",
                "smtpPort": 587,
                "smtpUser": "YOUR_EMAIL",
                "smtpPassword": "YOUR_PASSWORD"
            },
            "google": {
                "clientId": "YOUR_GOOGLE_CLIENT_ID",
                "clientSecret": "YOUR_GOOGLE_CLIENT_SECRET",
                "folderId": "YOUR_GOOGLE_DRIVE_FOLDER_ID",
                "calendarId": "primary"
            },
            "openai": {
                "apiKey": "YOUR_OPENAI_API_KEY"
            },
            "stripe": {
                "secretKey": "YOUR_STRIPE_SECRET_KEY"
            },
            "crm": {
                "apiUrl": "YOUR_CRM_API_URL",
                "apiKey": "YOUR_CRM_API_KEY"
            },
            "jira": {
                "baseUrl": "YOUR_JIRA_URL",
                "email": "YOUR_JIRA_EMAIL",
                "apiToken": "YOUR_JIRA_API_TOKEN"
            },
            "hr": {
                "apiUrl": "YOUR_HR_SYSTEM_API_URL",
                "apiKey": "YOUR_HR_SYSTEM_API_KEY"
            },
            "support": {
                "apiUrl": "YOUR_SUPPORT_SYSTEM_API_URL",
                "apiKey": "YOUR_SUPPORT_SYSTEM_API_KEY"
            }
        }
        
        self.runtime.record_outcome(
            decision_id=self.node_id,
            success=True,
            result={"pipelines_merged": len(pipelines), "total_nodes": len(merged["nodes"])},
            summary=f"Merged {len(pipelines)} pipelines with {len(merged['nodes'])} total nodes"
        )
        
        return {
            "merged_workflow": merged,
            "pipelines_merged": len(pipelines)
        }