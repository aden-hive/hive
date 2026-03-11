# core/examples/data_analysis_agent.py

import pandas as pd
from core.framework.agents.agent import Agent

class DataAnalysisAgent(Agent):
    def __init__(self, config):
        super().__init__(config)
        self.data = None

    def load_data(self, file_path):
        self.data = pd.read_csv(file_path)

    def generate_summary(self):
        if self.data is None:
            return "No data loaded."
        return self.data.describe()

    def answer_question(self, question):
        if self.data is None:
            return "No data loaded."
        # Simple question answering logic
        if "mean" in question.lower():
            column = question.split("of")[-1].strip()
            if column in self.data.columns:
                return f"The mean of {column} is {self.data[column].mean()}."
        return "I'm sorry, I can't answer that question."

# Example usage
if __name__ == "__main__":
    agent = DataAnalysisAgent(config={})
    agent.load_data("path/to/your/dataset.csv")
    print(agent.generate_summary())
    print(agent.answer_question("What is the mean of column_name?"))