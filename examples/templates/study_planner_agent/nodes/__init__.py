"""Node definitions for Study Planner Agent."""

from framework.graph import NodeSpec


# -------------------------
# Intake Node
# -------------------------
intake_node = NodeSpec(
    id="intake",
    name="Intake",
    description="Collect study requirements from the user",
    node_type="llm_generate",
    system_prompt=(
        "You are a study planning assistant.\n"
        "Your job is to understand the user's study requirements.\n"
        "Extract the following from the user input:\n"
        "- Subjects\n"
        "- Deadlines or exam dates\n"
        "- Difficulty level (if mentioned)\n"
        "- Daily available study hours\n\n"
        "Return the extracted information in a structured summary."
    ),
    client_facing=True,
)

# -------------------------
# Research Node
# -------------------------
research_node = NodeSpec(
    id="research",
    name="Prioritize Subjects",
    description="Analyze and prioritize subjects",
    node_type="llm_generate",
    system_prompt=(
        "You are an academic planning assistant.\n"
        "Based on the subjects, deadlines, and difficulty levels:\n"
        "- Prioritize subjects by urgency and difficulty.\n"
        "- Decide how much time should be allocated to each subject.\n"
        "- Ensure the total time per day does not exceed available hours.\n\n"
        "Return a prioritized subject list with suggested daily time allocation."
    ),
)

# -------------------------
# Compile Plan Node
# -------------------------
compile_report_node = NodeSpec(
    id="compile-report",
    name="Generate Study Plan",
    description="Create the final study schedule",
    node_type="llm_generate",
    system_prompt=(
        "You are a study planner.\n"
        "Create a clear day-by-day study schedule.\n\n"
        "Rules:\n"
        "- Follow the subject priorities.\n"
        "- Do not exceed available daily study hours.\n"
        "- Balance subjects across days.\n"
        "- Keep the plan realistic and simple.\n\n"
        "Output format:\n"
        "Day 1:\n"
        "- Subject A: 2 hours\n"
        "- Subject B: 1 hour\n\n"
        "Day 2:\n"
        "- Subject C: 2 hours\n"
        "- Subject A: 1 hour\n"
    ),
    terminal=True,
)

__all__ = [
    "intake_node",
    "research_node",
    "compile_report_node",
]
