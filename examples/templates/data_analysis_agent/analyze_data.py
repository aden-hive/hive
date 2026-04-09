# examples/templates/data_analysis_agent/analyze_data.py

import pandas as pd


class DataAnalysisAgent:
    def __init__(self, file_path):
        print(f"Analyzing dataset: {file_path}")
        self.df = pd.read_csv(file_path)

    def summary_statistics(self):
        numerical_cols = self.df.select_dtypes(include='number')
        summary = numerical_cols.describe().transpose()
        summary['mode'] = numerical_cols.mode().iloc[0]
        return summary[['mean', '50%', 'mode', 'min', 'max']]

    def missing_values(self):
        return self.df.isnull().sum()

    def department_distribution(self):
        if 'Department' in self.df.columns:
            return self.df['Department'].value_counts()
        return "No 'Department' column found."

    def correlations(self):
        numerical_cols = self.df.select_dtypes(include='number')
        return numerical_cols.corr()

    def avg_salary_by_department(self):
        if 'Department' in self.df.columns and 'Salary' in self.df.columns:
            return self.df.groupby('Department')['Salary'].mean()
        return "Required columns not found."

    def analyze(self):
        print("\n--- SUMMARY STATISTICS ---")
        print(self.summary_statistics())

        print("\n--- MISSING VALUES ---")
        print(self.missing_values())

        print("\n--- DEPARTMENT DISTRIBUTION ---")
        print(self.department_distribution())

        print("\n--- CORRELATIONS ---")
        print(self.correlations())

        print("\n--- AVG SALARY BY DEPARTMENT ---")
        result = self.avg_salary_by_department()
        if isinstance(result, pd.Series):
            print(result.fillna("No data"))  # Only convert for display
        else:
            print(result)


if __name__ == "__main__":
    import sys

    if len(sys.argv) < 2:
        print("Usage: python analyze_data.py <csv_file>")
    else:
        agent = DataAnalysisAgent(sys.argv[1])
        agent.analyze()