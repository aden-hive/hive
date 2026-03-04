""" Node definations for Data-Analysis Agent. """
from framework.graph import NodeSpec

# Node 1 - Intake

intake_node = NodeSpec(
    id ="intake",
    name = "Dataset Intake",
    description = "Receieve dataset path from the user",
    node_type = "event_loop",
    client_facing = True,
    max_node_visits = 0,
    input_keys = ["dataset_path"],
    output_keys = ["dataset_path"],
    sucess_criteria = "Dataset path has been provided by the user.",
    system_prompt = """\
                    You are a data analysis assistant.

                    Ask the user for a dataset path (CSV file).

                    Once the user provides the dataset path call:
                    set_output("dataset_path", "<path provided by the user>")
                    """,
    tools = [],
)

# Node 2 - Data Analsis:
analysis_node = NodeSpec(
    id="analysis",
    name="Dataset Analysis",
    description= "Analyze dataset and compute statistics",
    node_type = "event_loop",
    max_node_visits=0,
    input_keys=["dataset_path"],
    output_keys=["analysis_summary"],
    success_criteria="Dataset statistics have been computed.",
    system_prompt = """\
                    You are a data analyst.

                    Load the dataset from previous dataset_path.

                    Compute:
                    - Number of rows
                    - Number of columns
                    - Numneric columns means

                    After computing statistics call:
                    set_output("analysis_summary", "summary of the dataet statistics")
                    """,
    tools =[],
)

# Node 3 - Report:

report_node = NodeSpec(
    id="report",
    name="Generate Report",
    description="Generate a summary report of dataset analysis",
    node_type="event_loop",
    client_facing=True,
    max_node_visits=0,
    input_keys=["analysis_summary"],
    output_keys=["report"],
    success_criteria="A dataset summary report has been presented to the user.",
    system_prompt="""\
                  Present the dataset analysis summary clearly.

                  Include:
                  - Number of rows
                  - Number of columns
                  - Numeric column insights

                  Then call:
                  set_output("report", "dataset analysis report")
                  """,
    tools=[],
)

__all__ = [
    "intake_node",
    "analysis_node",
    "report_node",
]
