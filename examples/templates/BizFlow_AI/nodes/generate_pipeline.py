"""Node for generating individual n8n pipeline JSON."""

from typing import Dict, Any
import json
from pathlib import Path

from framework.graph import BaseNode
from framework.runtime import Runtime
from framework.llm import LLMProvider


class GeneratePipelineNode(BaseNode):
    """Generate n8n workflow JSON for a specific pipeline type."""
    
    def __init__(self, node_id: str, runtime: Runtime, llm: LLMProvider, pipeline_type: str):
        super().__init__(node_id, runtime)
        self.llm = llm
        self.pipeline_type = pipeline_type
        
    async def execute(self, input_data: Dict[str, Any]) -> Dict[str, Any]:
        """Generate pipeline workflow."""
        parsed = input_data.get("parsed_requirements", {})
        
        # Pipeline-specific templates
        templates = {
            "cv_screening": self._generate_cv_pipeline,
            "signal_engine": self._generate_signal_pipeline,
            "revenue_monitor": self._generate_revenue_pipeline,
            "contract_watchdog": self._generate_contract_pipeline,
            "hr_monitor": self._generate_hr_pipeline
        }
        
        generator = templates.get(self.pipeline_type, self._generate_generic_pipeline)
        workflow = await generator(parsed)
        
        return {
            "pipeline_type": self.pipeline_type,
            "workflow": workflow
        }
    
    async def _generate_cv_pipeline(self, parsed: Dict) -> Dict:
        """Generate CV screening pipeline."""
        return {
            "name": "Smart CV → Job → Interview Auto-Pipeline",
            "nodes": [
                {
                    "name": "CV Webhook Trigger",
                    "type": "n8n-nodes-base.webhookTrigger",
                    "position": [250, 300],
                    "parameters": {
                        "path": "cv-submission",
                        "responseMode": "responseNode",
                        "options": {}
                    }
                },
                {
                    "name": "Google Drive Trigger",
                    "type": "n8n-nodes-base.googleDriveTrigger",
                    "position": [250, 500],
                    "parameters": {
                        "folderId": "{{$parameter.folderId}}",
                        "event": "fileAdded"
                    }
                },
                {
                    "name": "Merge CV Sources",
                    "type": "n8n-nodes-base.merge",
                    "position": [450, 400],
                    "parameters": {
                        "mode": "combine"
                    }
                },
                {
                    "name": "Extract Text from CV",
                    "type": "n8n-nodes-base.extractFromFile",
                    "position": [650, 400],
                    "parameters": {}
                },
                {
                    "name": "OpenAI CV Analyzer",
                    "type": "@n8n/n8n-nodes-langchain.openAi",
                    "position": [850, 400],
                    "parameters": {
                        "model": "gpt-4o-mini",
                        "systemPrompt": "You are an expert HR recruiter. Analyze the CV against job requirements and return a JSON with: match_score (0-100), strengths (array), concerns (array), decision (shortlist/reject/manual_review)",
                        "options": {
                            "responseFormat": "json_object"
                        }
                    }
                },
                {
                    "name": "Route by Decision",
                    "type": "n8n-nodes-base.switch",
                    "position": [1050, 400],
                    "parameters": {
                        "dataPropertyName": "decision",
                        "rules": [
                            {
                                "value": "shortlist",
                                "outputKey": "shortlist"
                            },
                            {
                                "value": "reject", 
                                "outputKey": "reject"
                            },
                            {
                                "value": "manual_review",
                                "outputKey": "review"
                            }
                        ]
                    }
                },
                {
                    "name": "Send Interview Invitation",
                    "type": "n8n-nodes-base.emailSend",
                    "position": [1250, 300],
                    "parameters": {
                        "fromEmail": "{{$parameter.fromEmail}}",
                        "toEmail": "{{$json.candidateEmail}}",
                        "subject": "Interview Invitation",
                        "text": "Dear {{$json.candidateName}},\n\nWe are pleased to invite you for an interview..."
                    }
                },
                {
                    "name": "Schedule Calendar Event",
                    "type": "n8n-nodes-base.googleCalendar",
                    "position": [1250, 400],
                    "parameters": {
                        "operation": "create",
                        "calendarId": "primary",
                        "summary": "Interview with {{$json.candidateName}}",
                        "start": "{{$now.plus(7, 'days').toISO()}}",
                        "end": "{{$now.plus(7, 'days').plus(1, 'hour').toISO()}}"
                    }
                },
                {
                    "name": "Send Rejection Email",
                    "type": "n8n-nodes-base.emailSend",
                    "position": [1250, 500],
                    "parameters": {
                        "fromEmail": "{{$parameter.fromEmail}}",
                        "toEmail": "{{$json.candidateEmail}}",
                        "subject": "Update on Your Application",
                        "text": "Dear {{$json.candidateName}},\n\nThank you for your interest..."
                    }
                },
                {
                    "name": "Create ATS Task",
                    "type": "n8n-nodes-base.httpRequest",
                    "position": [1250, 600],
                    "parameters": {
                        "method": "POST",
                        "url": "{{$parameter.atsApiUrl}}/tasks",
                        "authentication": "genericCredentialType",
                        "genericAuthType": "httpHeaderAuth",
                        "sendHeaders": True,
                        "headerParameters": {
                            "parameters": [
                                {
                                    "name": "Authorization",
                                    "value": "Bearer {{$parameter.atsApiKey}}"
                                }
                            ]
                        },
                        "sendBody": True,
                        "bodyParameters": {
                            "parameters": [
                                {
                                    "name": "title",
                                    "value": "Review CV: {{$json.candidateName}}"
                                },
                                {
                                    "name": "description",
                                    "value": "Manual review required for candidate"
                                }
                            ]
                        }
                    }
                }
            ],
            "connections": {
                "CV Webhook Trigger": {"main": [{"node": "Merge CV Sources", "type": "main", "index": 0}]},
                "Google Drive Trigger": {"main": [{"node": "Merge CV Sources", "type": "main", "index": 1}]},
                "Merge CV Sources": {"main": [{"node": "Extract Text from CV", "type": "main", "index": 0}]},
                "Extract Text from CV": {"main": [{"node": "OpenAI CV Analyzer", "type": "main", "index": 0}]},
                "OpenAI CV Analyzer": {"main": [{"node": "Route by Decision", "type": "main", "index": 0}]},
                "Route by Decision": {
                    "shortlist": [
                        {"node": "Send Interview Invitation", "type": "main", "index": 0},
                        {"node": "Schedule Calendar Event", "type": "main", "index": 0}
                    ],
                    "reject": [{"node": "Send Rejection Email", "type": "main", "index": 0}],
                    "review": [{"node": "Create ATS Task", "type": "main", "index": 0}]
                }
            }
        }
    
    async def _generate_signal_pipeline(self, parsed: Dict) -> Dict:
        """Generate signal decision engine pipeline."""
        return {
            "name": "Signal Decision Engine",
            "nodes": [
                {
                    "name": "Signal Webhook",
                    "type": "n8n-nodes-base.webhookTrigger",
                    "position": [250, 300],
                    "parameters": {
                        "path": "signal-webhook",
                        "responseMode": "responseNode",
                        "options": {}
                    }
                },
                {
                    "name": "OpenAI Signal Analyzer",
                    "type": "@n8n/n8n-nodes-langchain.openAi",
                    "position": [450, 300],
                    "parameters": {
                        "model": "gpt-4o-mini",
                        "systemPrompt": """You are a signal processing AI. Analyze the incoming signal and return JSON with:
                        - intent: customer/partner/internal
                        - urgency: low/medium/high/critical
                        - sentiment: positive/neutral/negative
                        - risk_flags: array of [security, compliance, churn, legal]
                        - confidence: 0-1
                        - recommended_action: notify_human/create_crm_task/escalate_management/open_support_ticket
                        """,
                        "options": {
                            "responseFormat": "json_object"
                        }
                    }
                },
                {
                    "name": "Route Signal",
                    "type": "n8n-nodes-base.switch",
                    "position": [650, 300],
                    "parameters": {
                        "dataPropertyName": "recommended_action",
                        "rules": [
                            {"value": "notify_human", "outputKey": "slack"},
                            {"value": "create_crm_task", "outputKey": "crm"},
                            {"value": "escalate_management", "outputKey": "escalate"},
                            {"value": "open_support_ticket", "outputKey": "support"}
                        ]
                    }
                },
                {
                    "name": "Send Slack Notification",
                    "type": "n8n-nodes-base.slack",
                    "position": [850, 200],
                    "parameters": {
                        "channel": "{{$parameter.slackChannel}}",
                        "text": "⚠️ Signal Alert\nIntent: {{$json.intent}}\nUrgency: {{$json.urgency}}\nContent: {{$json.content}}"
                    }
                },
                {
                    "name": "Create CRM Task",
                    "type": "n8n-nodes-base.httpRequest",
                    "position": [850, 300],
                    "parameters": {
                        "method": "POST",
                        "url": "{{$parameter.crmApiUrl}}/tasks",
                        "authentication": "genericCredentialType",
                        "genericAuthType": "httpHeaderAuth",
                        "sendHeaders": True,
                        "headerParameters": {
                            "parameters": [{"name": "Authorization", "value": "Bearer {{$parameter.crmApiKey}}"}]
                        }
                    }
                },
                {
                    "name": "Send Escalation Email",
                    "type": "n8n-nodes-base.emailSend",
                    "position": [850, 400],
                    "parameters": {
                        "fromEmail": "{{$parameter.fromEmail}}",
                        "toEmail": "{{$parameter.escalationEmail}}",
                        "subject": "⚠️ CRITICAL: Signal Escalation Required",
                        "text": "Critical signal detected: {{$json.content}}"
                    }
                },
                {
                    "name": "Create Support Ticket",
                    "type": "n8n-nodes-base.httpRequest",
                    "position": [850, 500],
                    "parameters": {
                        "method": "POST",
                        "url": "{{$parameter.supportApiUrl}}/tickets",
                        "authentication": "genericCredentialType",
                        "genericAuthType": "httpHeaderAuth",
                        "sendHeaders": True,
                        "headerParameters": {
                            "parameters": [{"name": "Authorization", "value": "Bearer {{$parameter.supportApiKey}}"}]
                        }
                    }
                }
            ],
            "connections": {
                "Signal Webhook": {"main": [{"node": "OpenAI Signal Analyzer", "type": "main", "index": 0}]},
                "OpenAI Signal Analyzer": {"main": [{"node": "Route Signal", "type": "main", "index": 0}]},
                "Route Signal": {
                    "slack": [{"node": "Send Slack Notification", "type": "main", "index": 0}],
                    "crm": [{"node": "Create CRM Task", "type": "main", "index": 0}],
                    "escalate": [{"node": "Send Escalation Email", "type": "main", "index": 0}],
                    "support": [{"node": "Create Support Ticket", "type": "main", "index": 0}]
                }
            }
        }
    
    async def _generate_revenue_pipeline(self, parsed: Dict) -> Dict:
        """Generate revenue leak detector pipeline."""
        return {
            "name": "Revenue Leak Detector",
            "nodes": [
                {
                    "name": "Daily Schedule Trigger",
                    "type": "n8n-nodes-base.scheduleTrigger",
                    "position": [250, 300],
                    "parameters": {
                        "rule": {
                            "hour": 9,
                            "minute": 0,
                            "triggerAtDay": "monday,tuesday,wednesday,thursday,friday"
                        }
                    }
                },
                {
                    "name": "Revenue Webhook",
                    "type": "n8n-nodes-base.webhookTrigger",
                    "position": [250, 450],
                    "parameters": {
                        "path": "revenue-events",
                        "responseMode": "responseNode"
                    }
                },
                {
                    "name": "Merge Revenue Sources",
                    "type": "n8n-nodes-base.merge",
                    "position": [450, 375],
                    "parameters": {"mode": "combine"}
                },
                {
                    "name": "Get Failed Payments",
                    "type": "n8n-nodes-base.httpRequest",
                    "position": [450, 300],
                    "parameters": {
                        "method": "GET",
                        "url": "https://api.stripe.com/v1/charges?status=failed&created[gte]={{$now.minus(7, 'days').unix()}}",
                        "authentication": "genericCredentialType",
                        "genericAuthType": "httpHeaderAuth",
                        "sendHeaders": True,
                        "headerParameters": {
                            "parameters": [{"name": "Authorization", "value": "Bearer {{$parameter.stripeSecretKey}}"}]
                        }
                    }
                },
                {
                    "name": "Get Stale Leads",
                    "type": "n8n-nodes-base.httpRequest",
                    "position": [450, 350],
                    "parameters": {
                        "method": "GET",
                        "url": "{{$parameter.crmApiUrl}}/leads?status=contacted&last_contact[lt]={{$now.minus(14, 'days').toISO()}}",
                        "authentication": "genericCredentialType",
                        "genericAuthType": "httpHeaderAuth",
                        "sendHeaders": True,
                        "headerParameters": {
                            "parameters": [{"name": "Authorization", "value": "Bearer {{$parameter.crmApiKey}}"}]
                        }
                    }
                },
                {
                    "name": "Get At-Risk Subscriptions",
                    "type": "n8n-nodes-base.httpRequest",
                    "position": [450, 400],
                    "parameters": {
                        "method": "GET",
                        "url": "https://api.stripe.com/v1/subscriptions?status=active&current_period_end[lt]={{$now.plus(30, 'days').unix()}}",
                        "authentication": "genericCredentialType",
                        "genericAuthType": "httpHeaderAuth",
                        "sendHeaders": True,
                        "headerParameters": {
                            "parameters": [{"name": "Authorization", "value": "Bearer {{$parameter.stripeSecretKey}}"}]
                        }
                    }
                },
                {
                    "name": "OpenAI Revenue Analyzer",
                    "type": "@n8n/n8n-nodes-langchain.openAi",
                    "position": [650, 375],
                    "parameters": {
                        "model": "gpt-4o-mini",
                        "systemPrompt": """You are a revenue protection AI. Analyze the revenue data and return JSON with:
                        - leak_type: failed_payment/abandoned_lead/renewal_risk/churn_detected
                        - risk_level: low/medium/high/critical
                        - estimated_impact: number (USD)
                        - confidence: 0-1
                        - recommended_action: retry_payment/notify_finance/create_sales_task/trigger_retention_flow/escalate_management/ignore
                        """,
                        "options": {"responseFormat": "json_object"}
                    }
                },
                {
                    "name": "Route Revenue Actions",
                    "type": "n8n-nodes-base.switch",
                    "position": [850, 375],
                    "parameters": {
                        "dataPropertyName": "recommended_action",
                        "rules": [
                            {"value": "retry_payment", "outputKey": "retry"},
                            {"value": "notify_finance", "outputKey": "slack"},
                            {"value": "create_sales_task", "outputKey": "crm"},
                            {"value": "trigger_retention_flow", "outputKey": "email"},
                            {"value": "escalate_management", "outputKey": "escalate"},
                            {"value": "ignore", "outputKey": "ignore"}
                        ]
                    }
                },
                {
                    "name": "Retry Payment",
                    "type": "n8n-nodes-base.httpRequest",
                    "position": [1050, 200],
                    "parameters": {
                        "method": "POST",
                        "url": "https://api.stripe.com/v1/charges",
                        "authentication": "genericCredentialType",
                        "genericAuthType": "httpHeaderAuth",
                        "sendHeaders": True,
                        "headerParameters": {
                            "parameters": [{"name": "Authorization", "value": "Bearer {{$parameter.stripeSecretKey}}"}]
                        }
                    }
                },
                {
                    "name": "Notify Finance Slack",
                    "type": "n8n-nodes-base.slack",
                    "position": [1050, 300],
                    "parameters": {
                        "channel": "{{$parameter.financeSlackChannel}}",
                        "text": "💰 Revenue Leak Detected\nType: {{$json.leak_type}}\nImpact: ${{$json.estimated_impact}}"
                    }
                },
                {
                    "name": "Create Sales Task",
                    "type": "n8n-nodes-base.httpRequest",
                    "position": [1050, 400],
                    "parameters": {
                        "method": "POST",
                        "url": "{{$parameter.crmApiUrl}}/tasks",
                        "authentication": "genericCredentialType",
                        "genericAuthType": "httpHeaderAuth",
                        "sendHeaders": True,
                        "headerParameters": {
                            "parameters": [{"name": "Authorization", "value": "Bearer {{$parameter.crmApiKey}}"}]
                        }
                    }
                },
                {
                    "name": "Send Retention Email",
                    "type": "n8n-nodes-base.emailSend",
                    "position": [1050, 500],
                    "parameters": {
                        "fromEmail": "{{$parameter.fromEmail}}",
                        "toEmail": "{{$json.customerEmail}}",
                        "subject": "We'd love to keep you!",
                        "text": "We noticed your subscription is ending soon. Here's a special offer..."
                    }
                },
                {
                    "name": "Escalate to Management",
                    "type": "n8n-nodes-base.emailSend",
                    "position": [1050, 600],
                    "parameters": {
                        "fromEmail": "{{$parameter.fromEmail}}",
                        "toEmail": "{{$parameter.executiveEmail}}",
                        "subject": "🚨 CRITICAL: Major Revenue Leak Detected",
                        "text": "Critical revenue leak: {{$json.leak_type}} with impact ${{$json.estimated_impact}}"
                    }
                }
            ],
            "connections": {
                "Daily Schedule Trigger": {"main": [{"node": "Get Failed Payments", "type": "main", "index": 0}]},
                "Revenue Webhook": {"main": [{"node": "Merge Revenue Sources", "type": "main", "index": 1}]},
                "Get Failed Payments": {"main": [{"node": "Merge Revenue Sources", "type": "main", "index": 0}]},
                "Get Stale Leads": {"main": [{"node": "Merge Revenue Sources", "type": "main", "index": 1}]},
                "Get At-Risk Subscriptions": {"main": [{"node": "Merge Revenue Sources", "type": "main", "index": 2}]},
                "Merge Revenue Sources": {"main": [{"node": "OpenAI Revenue Analyzer", "type": "main", "index": 0}]},
                "OpenAI Revenue Analyzer": {"main": [{"node": "Route Revenue Actions", "type": "main", "index": 0}]},
                "Route Revenue Actions": {
                    "retry": [{"node": "Retry Payment", "type": "main", "index": 0}],
                    "slack": [{"node": "Notify Finance Slack", "type": "main", "index": 0}],
                    "crm": [{"node": "Create Sales Task", "type": "main", "index": 0}],
                    "email": [{"node": "Send Retention Email", "type": "main", "index": 0}],
                    "escalate": [{"node": "Escalate to Management", "type": "main", "index": 0}]
                }
            }
        }
    
    async def _generate_generic_pipeline(self, parsed: Dict) -> Dict:
        """Generate generic pipeline for unimplemented types."""
        return {
            "name": f"{self.pipeline_type.replace('_', ' ').title()} Pipeline",
            "nodes": [
                {
                    "name": "Trigger",
                    "type": "n8n-nodes-base.webhookTrigger",
                    "position": [250, 300],
                    "parameters": {"path": f"{self.pipeline_type}-webhook"}
                },
                {
                    "name": "OpenAI Analyzer",
                    "type": "@n8n/n8n-nodes-langchain.openAi",
                    "position": [450, 300],
                    "parameters": {
                        "model": "gpt-4o-mini",
                        "systemPrompt": "Analyze the input and make decisions",
                        "options": {"responseFormat": "json_object"}
                    }
                },
                {
                    "name": "Route Actions",
                    "type": "n8n-nodes-base.switch",
                    "position": [650, 300],
                    "parameters": {
                        "dataPropertyName": "action",
                        "rules": [{"value": "default", "outputKey": "default"}]
                    }
                },
                {
                    "name": "Default Action",
                    "type": "n8n-nodes-base.noOp",
                    "position": [850, 300]
                }
            ]
        }