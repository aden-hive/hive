# Data Analysis Agent Template

## Overview

This template provides a simple and reusable data analysis agent for CSV datasets using Python and pandas. It is designed to perform basic exploratory data analysis (EDA) and generate useful insights from structured data.

The template is beginner-friendly and can be easily extended for more advanced use cases.

---

## Features

- Load and analyze CSV datasets
- Generate summary statistics (mean, median, mode, min, max)
- Detect and report missing values
- Compute correlations between numerical variables
- Analyze categorical distributions
- Perform group-based aggregations (e.g., average salary by department)
- Command-line interface for ease of use

---

## Project Structure

```

examples/templates/data_analysis_agent/
│
├── analyze_data.py    # Main analysis script
├── sample.csv         # Example dataset
└── README.md          # Documentation

````

---

## Requirements

- Python 3.x
- pandas

Install dependencies:

```bash
pip install pandas
````

---

## Usage

Run the script from the command line:

```bash
python analyze_data.py <csv_file>
```

Example:

```bash
python analyze_data.py sample.csv
```

---

## Example Output

```
Analyzing dataset: sample.csv

--- SUMMARY STATISTICS ---
           mean      50%     mode      min      max
Age        31.8     30.0     25.0     25.0     40.0
Salary  61250.0  62500.0  50000.0  50000.0  70000.0

--- MISSING VALUES ---
Salary        1

--- DEPARTMENT DISTRIBUTION ---
HR             2
Engineering    2
Marketing      1

--- CORRELATIONS ---
           Age  Salary
Age     1.0000  0.9135
Salary  0.9135  1.0000

--- AVG SALARY BY DEPARTMENT ---
Engineering    65000.0
HR             57500.0
Marketing      No data
```

---

## Notes

* The script automatically detects numerical columns for statistical analysis.
* Missing values are reported explicitly.
* If required columns are missing (e.g., `Department`, `Salary`), the script handles it gracefully.
* The template is designed to be extended with additional analysis functions or visualizations.

---

## Extending the Template

We can extend this template by adding:

* Visualization support (matplotlib, seaborn)
* Advanced statistical analysis
* Query-based data interaction
* Integration with LLM-based agents

