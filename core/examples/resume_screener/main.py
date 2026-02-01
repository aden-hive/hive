import asyncio
import json
import os
from dotenv import load_dotenv

# Load API keys
load_dotenv()

from framework.graph.node import NodeSpec
from framework.graph.edge import EdgeSpec, EdgeCondition, GraphSpec
from framework.graph.goal import Goal
from framework.graph.executor import GraphExecutor
from framework.graph.output_cleaner import CleansingConfig 
from framework.runtime.core import Runtime
from framework.llm.provider import LLMProvider, LLMResponse
from framework.llm.litellm import LiteLLMProvider

# --- 1. Define a Robust Mock LLM (Fallback) ---

class MockLLM(LLMProvider):
    """
    A Fake LLM that returns pre-set JSON answers.
    Used when no API keys are available.
    """
    
    def complete(self, messages, system="", **kwargs):
        # Flatten messages to a lower-case string for easy keyword matching
        prompt_dump = (json.dumps(messages) + str(system)).lower()
        
        content = ""
        step_name = "unknown"

        # 1. Analyze Resume
        if "resume_text" in prompt_dump:
             step_name = "Analyze Resume"
             content = json.dumps({
                 "candidate_profile": {
                     "name": "Jane Doe",
                     "skills": ["Python", "Rust", "AWS", "Docker"],
                     "experience": "5 years at TechCorp (Senior Eng)",
                     "summary": "Strong backend engineer with AI experience."
                 }
             })
        
        # 2. Score Candidate
        elif "job_description" in prompt_dump:
            step_name = "Score Candidate"
            content = json.dumps({
                "score_report": {
                    "score": 85,
                    "reasoning": "Candidate matches 90% of requirements. Strong Python/AWS."
                }
            })

        # 3. Human Review (Auto-Simulated for Mock Mode)
        elif "score_report" in prompt_dump:
            step_name = "Human Review (Auto-Simulated)"
            content = json.dumps({
                "human_decision": "interview"
            })

        # 4. Draft Invite
        elif "interview" in prompt_dump:
            step_name = "Draft Invite"
            content = json.dumps({
                "final_email": "Subject: Interview Invitation\n\nHi Jane,\n\nWe'd love to chat!"
            })
            
        # 5. Draft Rejection
        elif "reject" in prompt_dump or "others" in prompt_dump:
            step_name = "Draft Rejection"
            content = json.dumps({
                "final_email": "Subject: Application Update\n\nHi Jane,\n\nWe are moving forward with others."
            })
        
        else:
            step_name = "Unknown Step"
            content = json.dumps({"error": "Unknown step", "result": "generic response"})

        print(f"    Mock LLM serving step: [{step_name}]")
        
        return LLMResponse(
            content=content,
            model="mock-model-free",
            input_tokens=10,
            output_tokens=50
        )

    def complete_with_tools(self, messages, system, tools, tool_executor, **kwargs):
        return self.complete(messages, system, **kwargs)

# --- 2. Define the Nodes ---

analyze_node = NodeSpec(
    id="analyze_resume",
    name="Resume Analyzer",
    description="Analyzes the raw resume text to extract structured data.",
    node_type="llm_generate",
    input_keys=["resume_text"],
    output_keys=["candidate_profile"],
    validate_output=False 
)

score_node = NodeSpec(
    id="score_candidate",
    name="Candidate Scorer",
    description="Compares the candidate profile against the job description.",
    node_type="llm_generate",
    input_keys=["candidate_profile", "job_description"],
    output_keys=["score_report"], 
)

human_node = NodeSpec(
    id="human_decision",
    name="Hiring Manager Review",
    description="Pauses execution for a human to review the score.",
    node_type="human_input",
    input_keys=["score_report"],
    output_keys=["human_decision"]
)

invite_node = NodeSpec(
    id="draft_invite",
    name="Draft Invite Email",
    description="Generates an interview invitation email.",
    node_type="llm_generate",
    input_keys=["candidate_profile", "human_decision"], 
    output_keys=["final_email"]
)

reject_node = NodeSpec(
    id="draft_rejection",
    name="Draft Rejection Email",
    description="Generates a polite rejection email.",
    node_type="llm_generate",
    input_keys=["candidate_profile", "human_decision"],
    output_keys=["final_email"]
)

# --- 3. Define the Graph ---

nodes = [analyze_node, score_node, human_node, invite_node, reject_node]

edges = [
    # Edge 1: Analyze -> Score
    EdgeSpec(
        id="e1", 
        source="analyze_resume", 
        target="score_candidate",
        input_mapping={
            "candidate_profile": "candidate_profile",
            "job_description": "job_description" 
        }
    ),

    # Edge 2: Score -> Human
    EdgeSpec(
        id="e2", 
        source="score_candidate", 
        target="human_decision",
        input_mapping={
            "score_report": "score_report"
        }
    ),
    
    # Branch 1: Human -> Draft Invite
    EdgeSpec(
        id="e4",
        source="human_decision", 
        target="draft_invite",
        condition=EdgeCondition.CONDITIONAL,
        condition_expr="'interview' in human_decision.lower()",
        input_mapping={
            "candidate_profile": "candidate_profile",
            "human_decision": "human_decision" 
        }
    ),
    
    # Branch 2: Human -> Draft Rejection
    EdgeSpec(
        id="e5",
        source="human_decision", 
        target="draft_rejection",
        condition=EdgeCondition.CONDITIONAL,
        condition_expr="'interview' not in human_decision.lower()",
        input_mapping={
            "candidate_profile": "candidate_profile",
            "human_decision": "human_decision"
        }
    ),
]

graph = GraphSpec(
    id="resume_screener",
    goal_id="screen_001",
    entry_node="analyze_resume",
    nodes=nodes,
    edges=edges,
    max_steps=10
)

# --- 4. Run It ---

async def main():
    runtime = Runtime(storage_path="./storage")
    
    # --- SMART LLM SELECTION ---
    llm = None
    if os.getenv("OPENAI_API_KEY"):
        print("🔑 API Key found! Using Real LLM: gpt-4o")
        llm = LiteLLMProvider(model="gpt-4o")
    elif os.getenv("ANTHROPIC_API_KEY"):
        print("🔑 API Key found! Using Real LLM: claude-3-5-sonnet")
        llm = LiteLLMProvider(model="claude-3-5-sonnet-20240620")
    elif os.getenv("CEREBRAS_API_KEY"):
        print("🔑 API Key found! Using Real LLM: cerebras/llama3-70b")
        llm = LiteLLMProvider(model="cerebras/llama3-70b-8192")
    else:
        print("⚠️ No API Key found. Using Mock LLM (Free Mode).")
        llm = MockLLM()

    # Disable cleansing to allow flexible data flow from Global Memory
    executor = GraphExecutor(
        runtime=runtime, 
        llm=llm,
        cleansing_config=CleansingConfig(enabled=False)
    )

    sample_resume = """
    Jane Doe
    Software Engineer
    Experience: 
    - 5 years in Python, AWS, Docker.
    - Built AI Agents using LLMs.
    """ 

    sample_jd = """
    Job: Senior AI Engineer
    Requirements: 
    - Python, AWS, Docker
    - Experience building Agents
    """

    print(" Starting Resume Screener Agent...")
    
    result = await executor.execute(
        graph=graph,
        goal=Goal(id="screen_jane", name="Screen Candidate", description="Evaluate Jane Doe for AI Engineer role"),
        input_data={
            "resume_text": sample_resume,
            "job_description": sample_jd
        }
    )

    if result.success:
        print("\n✅ Process Complete!")
        print("-" * 40)
        
        decision = result.output.get('human_decision')
        # Handle potential stringified JSON from Mock/LLM
        if isinstance(decision, str) and "{" in decision:
            try:
                decision = json.loads(decision).get("human_decision", decision)
            except:
                pass
        print(f"Human Decision: {decision}")
        
        print("-" * 40)
        print("📨 Final Email Draft:\n")
        
        email_data = result.output.get("final_email", "")
        if isinstance(email_data, str) and "{" in email_data:
            try:
                print(json.loads(email_data).get("final_email", email_data))
            except:
                print(email_data)
        else:
            print(email_data)
    else:
        print(f"\n Error: {result.error}")

if __name__ == "__main__":
    asyncio.run(main())