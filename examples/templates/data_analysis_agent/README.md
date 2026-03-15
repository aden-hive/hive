# Data Analysis Agent

A template agent that analyzes CSV datasets using pandas. Upload a CSV file, ask questions about the data, and receive a structured HTML report with EDA results.

## What It Does

1. **Intake** — Accepts a CSV file path and an optional analysis question
2. **Load & Explore** — Loads the CSV with pandas, computes shape, dtypes, null counts, and descriptive statistics
3. **Answer** — Answers the specific analysis goal, or surfaces the top findings for general EDA
4. **Report** — Delivers results as an HTML report and interactive summary

## Usage

```bash
hive run examples/templates/data_analysis_agent --input '{"csv_path": "/path/to/data.csv"}'
```

With a specific question:
```bash
hive run examples/templates/data_analysis_agent --input '{
  "csv_path": "/path/to/sales.csv",
  "analysis_goal": "Which product category has the highest revenue?"
}'
```

## Example Analysis

**Input:** `sales.csv` with columns `date, product, category, quantity, price`

**EDA Summary:**
- Shape: 10,000 rows × 5 columns
- No null values found
- `price` range: $0.99 – $499.99
- `category`: 8 unique values

**Findings:**
- Electronics accounts for 42% of total revenue
- Q4 shows 35% higher sales volume than Q1–Q3
- 3 products account for 60% of all units sold

## Requirements

Requires the `execute_python` tool to run pandas code. pandas must be installed in the agent's Python environment:

```bash
pip install pandas
```

## Outputs

| Field | Description |
|---|---|
| `eda_summary` | Shape, column info, stats, data quality notes |
| `column_info` | Per-column dtype, null count, unique values |
| `sample_rows` | First 5 rows of the dataset |
| `analysis_result` | Answer to the analysis goal |
| `findings` | Bulleted list of key insights |
