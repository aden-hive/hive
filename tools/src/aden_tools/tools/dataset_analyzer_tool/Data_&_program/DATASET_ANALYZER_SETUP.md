# Dataset Analyzer Tool - Complete Setup & Usage Guide

## ✅ Implementation Complete

The Dataset Analyzer MCP Tool has been successfully implemented and integrated into the Aden framework. Here's what was created:

## 📂 Created Files

```
src/aden_tools/tools/dataset_analyzer_tool/
├── __init__.py                    # Module initialization
├── dataset_analyzer_tool.py       # Main tool implementation (250+ lines)
└── README.md                      # Comprehensive documentation

MODIFIED:
└── src/aden_tools/tools/__init__.py  # Added dataset_analyzer registration
```

## 🚀 Quick Start

### 1. Install Dependencies

```bash
cd c:\Users\manty\Desktop\Hive

# Using uv (recommended)
uv pip install pandas numpy

# Or using pip
pip install pandas numpy
```

### 2. Start MCP Server

```bash
# Start the Aden MCP server (the tool loads automatically)
aden run

# Or directly with Python
python -m your_mcp_server_module
```

### 3. Use the Tool in Agent Code

```python
# Call the tool from your agent
result = dataset_analyze(
    path="datasets/sales.csv",
    workspace_id="workspace_1",
    agent_id="agent_1",
    session_id="session_1"
)

print(result)
```

## 📊 Tool Features

### What It Does

✅ **Analyzes CSV Datasets**
- Row and column counts
- Data type detection (numeric vs categorical)

✅ **Data Quality Analysis**
- Missing value detection
- Summary statistics (mean, std, min, max, percentiles)
- Correlation analysis

✅ **Machine Learning Recommendations**
- Auto-detects problem type (classification, regression, unsupervised)
- Recommends algorithms based on dataset size
- Follows scikit-learn cheat sheet logic

✅ **Security**
- Sandboxed file access (cannot escape workspace)
- Uses `get_secure_path()` for security

### Output Example

```json
{
  "success": true,
  "path": "datasets/sales.csv",
  "rows": 1000,
  "columns": 15,
  "numeric_columns": ["price", "sales", "profit"],
  "categorical_columns": ["product", "region"],
  "missing_values": {
    "price": 0,
    "sales": 2,
    "product": 0
  },
  "summary_statistics": {
    "price": {
      "count": 1000.0,
      "mean": 599.5,
      "std": 345.3,
      "min": 10.0,
      "25%": 299.75,
      "50%": 599.5,
      "75%": 899.25,
      "max": 1999.0
    }
  },
  "top_correlations": {
    "price": {
      "sales": 0.82,
      "profit": 0.75
    }
  },
  "detected_target_column": "profit",
  "problem_type": "regression",
  "recommended_algorithms": [
    "Ridge Regression",
    "Elastic Net",
    "Support Vector Regression"
  ]
}
```

## 🎯 Usage Scenarios

### Scenario 1: Basic Dataset Analysis

```python
# Analyze a new dataset
result = dataset_analyze(
    path="data/customer_data.csv",
    workspace_id="workspace_1",
    agent_id="agent_1",
    session_id="session_1"
)

# Check dataset structure
print(f"Dataset has {result['rows']} rows and {result['columns']} columns")
print(f"Missing values: {result['missing_values']}")
```

### Scenario 2: Target-Based Analysis

```python
# Analyze dataset with specific target column
result = dataset_analyze(
    path="data/customer_churn.csv",
    workspace_id="workspace_1",
    agent_id="agent_1",
    session_id="session_1",
    target_column="churn"  # Predict churn
)

print(f"Problem Type: {result['problem_type']}")
print(f"Recommended Algorithms: {result['recommended_algorithms']}")
```

### Scenario 3: Large Dataset Sampling

```python
# Analyze large dataset with sampling for speed
result = dataset_analyze(
    path="data/large_dataset.csv",
    workspace_id="workspace_1",
    agent_id="agent_1",
    session_id="session_1",
    sample_size=10000  # Analyze 10k rows instead of all
)

print(f"Analyzed {result['rows']} sampled rows")
```

## 🔍 Algorithm Recommendation Logic

### Classification (Target is Categorical)

**For datasets < 100,000 rows:**
- Linear SVC
- K-Neighbors Classifier
- Random Forest Classifier

**For datasets ≥ 100,000 rows:**
- SGD Classifier (scalable)
- Naive Bayes (fast)
- Gradient Boosting Classifier

### Regression (Target is Numerical)

**For datasets < 100,000 rows:**
- Ridge Regression
- Elastic Net
- Support Vector Regression

**For datasets ≥ 100,000 rows:**
- SGD Regressor (scalable)
- Random Forest Regressor
- Gradient Boosting Regressor

### Unsupervised Learning (No Target)

**For datasets < 10,000 rows:**
- K-Means
- Spectral Clustering
- Gaussian Mixture Model

**For datasets ≥ 10,000 rows:**
- Mini-Batch K-Means (scalable)
- Principal Component Analysis
- DBSCAN

## 🧪 Testing

### Create Test Dataset

```bash
# Create sample CSV
cat > test_data.csv << EOF
id,age,salary,department
1,25,50000,Sales
2,30,60000,IT
3,35,70000,Sales
4,40,80000,HR
5,45,90000,IT
EOF
```

### Run Test

```python
result = dataset_analyze(
    path="test_data.csv",
    workspace_id="w",
    agent_id="a",
    session_id="s",
    target_column="salary"
)

# Output should show:
# - 5 rows, 4 columns
# - numeric_columns: ['id', 'age', 'salary']
# - categorical_columns: ['department']
# - problem_type: 'regression'
# - recommended_algorithms: ['Ridge Regression', 'Elastic Net', 'Support Vector Regression']
```

## 🔒 Security Sandbox

The tool operates within a security sandbox:

```
workspace_1/
├─ agent_1/
│  ├─ session_1/
│  │  └─ dataset.csv  ✓ ACCESSIBLE
│  └─ session_2/
│     └─ dataset.csv  ✓ ACCESSIBLE
└─ agent_2/
   └─ session_1/
      └─ dataset.csv  ✓ DIFFERENT AGENT (isolated)
```

Agents cannot access:
- Files outside their workspace
- System files (`/etc/passwd`, `C:\Windows\System32`, etc.)
- Other agents' files

## 📝 API Reference

### Function: `dataset_analyze()`

```python
def dataset_analyze(
    path: str,                          # Required: CSV file path
    workspace_id: str,                  # Required: workspace ID
    agent_id: str,                      # Required: agent ID
    session_id: str,                    # Required: session ID
    target_column: str | None = None,   # Optional: target column name
    sample_size: int | None = None,     # Optional: sample size
) -> dict
```

**Parameters:**

| Name | Type | Required | Description |
|------|------|----------|-------------|
| `path` | str | Yes | Path to CSV dataset (relative to workspace) |
| `workspace_id` | str | Yes | Workspace identifier for sandboxing |
| `agent_id` | str | Yes | Agent identifier for sandboxing |
| `session_id` | str | Yes | Session identifier for sandboxing |
| `target_column` | str | No | Name of target column for supervised learning |
| `sample_size` | int | No | Number of rows to sample (for large datasets) |

**Returns:** Dictionary with analysis results

## ⚙️ Configuration

### Dependencies (in pyproject.toml)

```toml
[project]
dependencies = [
    "pandas>=2.0.0",
    "numpy>=1.24.0",
    "fastmcp>=0.1.0",
]
```

### Environment Setup

```bash
# Install all dependencies
uv sync

# Or install specific packages
uv pip install pandas numpy fastmcp
```

## 🐛 Troubleshooting

### Issue: "Dataset not found"
```
✓ Verify file exists in workspace
✓ Check path is relative to workspace root
✓ Verify workspace_id, agent_id, session_id match agent context
```

### Issue: "Only CSV files are supported"
```
✓ Ensure file has .csv extension
✓ Rename other formats to .csv first
✓ Or use csv_tool/excel_tool for other formats
```

### Issue: "CSV parsing error"
```
✓ Check CSV format is valid
✓ Verify encoding (default: UTF-8)
✓ Ensure proper comma separation
✓ Check for special characters in headers
```

### Issue: Out of Memory on Large Files
```
✓ Use sample_size parameter to analyze subset
✓ Process dataset in chunks
✓ Increase system RAM if possible
```

## 🚀 Next Steps

### Option 1: Basic Usage
The tool works immediately with any CSV file. Start using it in your agents!

### Option 2: Extend with AutoML
Add automatic model training:

```python
@mcp.tool()
def train_recommended_model(
    path: str,
    workspace_id: str,
    agent_id: str,
    session_id: str,
    target_column: str
) -> dict:
    """Train the recommended algorithms and return best model."""
    # 1. Analyze dataset (use dataset_analyze)
    # 2. Train recommended algorithms
    # 3. Evaluate on holdout set
    # 4. Return best model as pickle
```

### Option 3: Add Visualization
Create plots for dataset insights:

```python
@mcp.tool()
def visualize_dataset(path: str, ...) -> str:
    """Generate correlation heatmap, distribution plots, etc."""
    # Uses matplotlib/seaborn
    # Returns PNG images or HTML
```

## 📚 Complete Files

### Implementation Files Created:

1. **dataset_analyzer_tool.py** (250+ lines)
   - Main analysis logic
   - ML recommendation engine
   - Security sandbox integration

2. **__init__.py** (3 lines)
   - Module initialization
   - Tool registration export

3. **README.md** (400+ lines)
   - Complete documentation
   - Examples and use cases
   - Troubleshooting guide

4. **SETUP_GUIDE.md** (this file)
   - Quick start instructions
   - Integration details
   - API reference

### Modified Files:

- **src/aden_tools/tools/__init__.py**
  - Added import: `from .dataset_analyzer_tool import register_tools as register_dataset_analyzer`
  - Added registration: `register_dataset_analyzer(mcp)`

## 📞 Support & Documentation

- **Full Documentation**: See `README.md` in the tool folder
- **Code Examples**: See usage scenarios above
- **API Reference**: See "API Reference" section
- **Test Examples**: See "Testing" section

## ✨ Summary

You now have a production-ready Dataset Analyzer tool that:

✅ Analyzes CSV datasets automatically
✅ Detects ML problem types (classification/regression/unsupervised)
✅ Recommends algorithms based on data characteristics and size
✅ Provides statistical insights and correlations
✅ Follows Aden's security sandbox pattern
✅ Integrates seamlessly with the MCP framework
✅ Handles errors gracefully
✅ Works with datasets of any size (with optional sampling)

Ready to use in AI agents for automated data science workflows!
