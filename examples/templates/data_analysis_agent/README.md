# Data Analysis Agent (Community)

## Built by https://github.com/gandharvk422

An autonomous agent that analyzes datasets and generates structured insights such as summary statistics, trends, and patterns. This template demonstrates how Hive agents can be used to automate exploratory data analysis workflows.

---

## Prerequisites

* **Python 3.11+** with `uv`
* **ANTHROPIC_API_KEY** — set in your `.env` file or environment

Optional:

* Additional data analysis tools or APIs depending on your workflow configuration.

---

## Quick Start

### Interactive Shell

```bash
cd examples/templates
uv run python -m data_analysis_agent shell
```

### CLI Run

```bash
# Run analysis on a dataset
uv run python -m data_analysis_agent run \
  --dataset "data.csv"
```

### TUI Dashboard

```bash
uv run python -m data_analysis_agent tui
```

### Validate & Info

```bash
uv run python -m data_analysis_agent validate
uv run python -m data_analysis_agent info
```

---

## Agent Graph

```
intake → analysis → report
```

| Node         | Purpose                                          | Client-Facing |
| ------------ | ------------------------------------------------ | :-----------: |
| **intake**   | Collect dataset input and analysis preferences   |       ✅       |
| **analysis** | Perform statistical analysis and detect patterns |               |
| **report**   | Generate structured insights and summary results |       ✅       |

---

## Input Format

```json
{
  "dataset": "data.csv"
}
```

The dataset should typically be a CSV file containing structured tabular data.

---

## Output

The agent generates structured insights including:

* 📊 **Summary Statistics** — mean, median, distributions, etc.
* 📈 **Trend Detection** — identifying patterns in the data
* 🔍 **Key Insights** — important observations derived from the dataset

Results may be saved locally depending on configuration and tool usage.

---

## Notes

This template provides a simple starting point for building Hive agents focused on data analysis workflows. It can be extended to support:

* Advanced statistical analysis
* Visualization generation
* Automated reporting pipelines
* Integration with external data sources
