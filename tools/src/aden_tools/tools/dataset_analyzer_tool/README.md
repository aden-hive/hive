# Dataset Analyzer Tool

A Machine Learning dataset analysis tool for the Aden MCP framework. Analyzes CSV datasets and automatically provides insights such as dataset statistics, missing values, feature types, correlations, ML task detection, and recommended algorithms.

## 📋 Features

The tool automatically analyzes datasets and returns:

### Dataset Statistics
- Number of rows
- Number of columns
- Numeric features
- Categorical features

### Data Quality Analysis
- Missing value detection
- Summary statistics (mean, std, min, max)
- Correlation analysis
- Feature type detection

### Machine Learning Suggestions
- Classification / Regression / Unsupervised detection
- Recommended algorithms following scikit-learn cheat sheet logic
- Size-aware algorithm recommendations

## 📁 Folder Structure

```
src/
 └─ aden_tools/
     └─ tools/
         └─ dataset_analyzer_tool/
             ├─ __init__.py
             ├─ dataset_analyzer_tool.py
             └─ README.md
```

## 🚀 Installation

### 1. Install Dependencies

```bash
uv pip install pandas numpy
```

Or with pip:

```bash
pip install pandas numpy
```

### 2. Verify Aden Environment

Ensure your project contains `src/aden_tools/`. If not, clone the Aden repository.

## 🔧 Tool Implementation

### File: `dataset_analyzer_tool.py`

Registers the MCP tool using:

```python
def register_tools(mcp: FastMCP) -> None
```

The MCP server loads this function to make the tool available to AI agents.

### Registering the Tool

The tool module should be registered in the tools loader. Ensure the module is included in your MCP server's tool registration pipeline.

## 📚 Tool API

### `dataset_analyze()`

Analyzes a CSV dataset and suggests ML algorithms.

#### Parameters

| Parameter | Type | Description |
|-----------|------|-------------|
| `path` | str | Path to dataset (relative to workspace) |
| `workspace_id` | str | Workspace identifier |
| `agent_id` | str | Agent identifier |
| `session_id` | str | Session identifier |
| `target_column` | str (optional) | Target variable name for supervised learning |
| `sample_size` | int (optional) | Number of rows to sample for faster analysis |

#### Returns

Dictionary containing:
- `success`: Analysis success status
- `path`: Dataset path
- `rows`: Number of rows
- `columns`: Number of columns
- `numeric_columns`: List of numeric feature names
- `categorical_columns`: List of categorical feature names
- `missing_values`: Count of missing values per column
- `summary_statistics`: Statistical summaries (mean, std, min, max for numeric columns)
- `top_correlations`: Top 3 correlations per numeric column
- `detected_target_column`: Detected or provided target column
- `problem_type`: 'classification', 'regression', or 'unsupervised'
- `recommended_algorithms`: List of recommended ML algorithms

## 💡 Usage Examples

### Basic Usage

```python
result = dataset_analyze(
    path="datasets/sales.csv",
    workspace_id="workspace_1",
    agent_id="agent_1",
    session_id="session_1"
)
```

### With Target Column

```python
result = dataset_analyze(
    path="datasets/sales.csv",
    workspace_id="workspace_1",
    agent_id="agent_1",
    session_id="session_1",
    target_column="profit"
)
```

### With Sampling

```python
result = dataset_analyze(
    path="large_dataset.csv",
    workspace_id="workspace_1",
    agent_id="agent_1",
    session_id="session_1",
    sample_size=10000  # Analyze first 10,000 rows
)
```

## 📊 Example Dataset

### Input CSV

```csv
product,price,sales,profit,region
Phone,500,200,150,Asia
Laptop,1200,120,100,Europe
Tablet,300,180,140,Asia
Desktop,800,90,70,North America
Monitor,200,250,180,Europe
Keyboard,50,500,400,Asia
```

### Output

```json
{
  "success": true,
  "path": "datasets/sales.csv",
  "rows": 6,
  "columns": 5,
  "numeric_columns": ["price", "sales", "profit"],
  "categorical_columns": ["product", "region"],
  "missing_values": {
    "product": 0,
    "price": 0,
    "sales": 0,
    "profit": 0,
    "region": 0
  },
  "summary_statistics": {
    "price": {
      "count": 6.0,
      "mean": 675.0,
      "std": 444.14,
      "min": 50.0,
      "25%": 237.5,
      "50%": 550.0,
      "75%": 1000.0,
      "max": 1200.0
    },
    "sales": {
      "count": 6.0,
      "mean": 221.67,
      "std": 150.07,
      ...
    }
  },
  "top_correlations": {
    "price": {
      "sales": -0.35,
      "profit": -0.28
    },
    "sales": {
      "profit": 0.82
    },
    "profit": {
      "sales": 0.82
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

## 🤖 Algorithm Recommendation Logic

The tool analyzes dataset properties and recommends algorithms following scikit-learn cheat sheet logic.

### Classification (Target is Categorical)

#### For datasets < 100,000 rows
- Linear SVC
- K-Neighbors Classifier
- Random Forest Classifier

#### For datasets ≥ 100,000 rows
- SGD Classifier (scalable)
- Naive Bayes (fast)
- Gradient Boosting Classifier

### Regression (Target is Numerical)

#### For datasets < 100,000 rows
- Ridge Regression
- Elastic Net
- Support Vector Regression

#### For datasets ≥ 100,000 rows
- SGD Regressor (scalable)
- Random Forest Regressor
- Gradient Boosting Regressor

### Unsupervised Learning (No Target Column)

#### For datasets < 10,000 rows
- K-Means
- Spectral Clustering
- Gaussian Mixture Model

#### For datasets ≥ 10,000 rows
- Mini-Batch K-Means (scalable)
- Principal Component Analysis
- DBSCAN

## 🔒 Security

The tool uses `get_secure_path()` from the security module to ensure agents cannot access files outside their sandbox.

### Sandbox Structure
```
workspace/
  ├─ agent_1/
  │   ├─ session_1/
  │   │   └─ dataset.csv  ✓ Accessible
  │   └─ session_2/
  │       └─ dataset.csv  ✓ Accessible
  └─ agent_2/
      └─ session_1/
          └─ dataset.csv  ✓ Different agent
```

Agents cannot read:
- `/etc/passwd`
- `C:/Windows/System32`
- Files outside their workspace sandbox

## ⚙️ Performance Options

### Large Dataset Analysis

For very large datasets, use sampling to speed up analysis:

```python
dataset_analyze(
    path="big_dataset.csv",
    workspace_id="workspace_1",
    agent_id="agent_1",
    session_id="session_1",
    sample_size=10000
)
```

**Benefits:**
- Faster analysis
- Lower memory usage
- Still provides representative insights

## 🧪 Testing the Tool

### Create Test File

Create `tests/tools/test_dataset_analyzer_tool.py`:

```python
import pytest
import pandas as pd
import tempfile
import os
from fastmcp import FastMCP
from aden_tools.tools.dataset_analyzer_tool import register_tools


@pytest.fixture
def sample_csv():
    """Create a sample CSV for testing."""
    data = {
        "id": [1, 2, 3, 4, 5],
        "age": [25, 30, 35, 40, 45],
        "salary": [50000, 60000, 70000, 80000, 90000],
        "department": ["Sales", "IT", "Sales", "HR", "IT"]
    }
    df = pd.DataFrame(data)
    
    with tempfile.NamedTemporaryFile(mode='w', suffix='.csv', delete=False) as f:
        df.to_csv(f.name, index=False)
        return f.name


def test_dataset_analyze_regression(sample_csv):
    """Test dataset analysis for regression problem."""
    mcp = FastMCP("test")
    register_tools(mcp)
    
    tool_fn = mcp._tool_manager._tools["dataset_analyze"].fn
    
    result = tool_fn(
        path=sample_csv,
        workspace_id="w",
        agent_id="a",
        session_id="s",
        target_column="salary"
    )
    
    assert result["success"] is True
    assert result["rows"] == 5
    assert result["columns"] == 4
    assert result["problem_type"] == "regression"
    assert "Ridge Regression" in result["recommended_algorithms"]


def test_dataset_analyze_classification(sample_csv):
    """Test dataset analysis for classification problem."""
    mcp = FastMCP("test")
    register_tools(mcp)
    
    tool_fn = mcp._tool_manager._tools["dataset_analyze"].fn
    
    result = tool_fn(
        path=sample_csv,
        workspace_id="w",
        agent_id="a",
        session_id="s",
        target_column="department"
    )
    
    assert result["success"] is True
    assert result["problem_type"] == "classification"
    assert "Linear SVC" in result["recommended_algorithms"]


def test_dataset_not_found():
    """Test error handling for missing file."""
    mcp = FastMCP("test")
    register_tools(mcp)
    
    tool_fn = mcp._tool_manager._tools["dataset_analyze"].fn
    
    result = tool_fn(
        path="nonexistent.csv",
        workspace_id="w",
        agent_id="a",
        session_id="s"
    )
    
    assert "error" in result
    assert "not found" in result["error"]


def test_empty_dataset():
    """Test error handling for empty datasets."""
    with tempfile.NamedTemporaryFile(mode='w', suffix='.csv', delete=False) as f:
        f.write("")
        f.flush()
        
        mcp = FastMCP("test")
        register_tools(mcp)
        
        tool_fn = mcp._tool_manager._tools["dataset_analyze"].fn
        
        result = tool_fn(
            path=f.name,
            workspace_id="w",
            agent_id="a",
            session_id="s"
        )
        
        assert "error" in result
```

### Run Tests

```bash
pytest tests/tools/test_dataset_analyzer_tool.py -v
```

## 💼 Use Cases

### Data Science Workflows
Automatically inspect datasets before training models and selecting algorithms.

### AutoML Pipelines
Provide algorithm recommendations for automatic model selection.

### Analytics Dashboards
Summarize dataset structure for business intelligence.

### Data Cleaning Pipelines
Detect missing values and data quality issues before processing.

### Feature Engineering
Analyze correlations to identify feature interactions.

## 📈 Example AI Workflow

Typical agent workflow:

```
1. User uploads dataset
        ↓
2. Agent calls dataset_analyze()
        ↓
3. Tool returns dataset summary
        ↓
4. Agent reviews recommended algorithms
        ↓
5. Agent trains recommended models
        ↓
6. Agent returns best performing model
```

## 🚀 Future Improvements

### AutoML Training
Automatically train all recommended models and return the best accuracy.

### Data Visualization
Generate plots for:
- Feature distribution histograms
- Correlation heatmaps
- Missing value patterns
- Feature importance rankings

### Feature Analysis
- Detect most important columns
- Identify feature interactions
- Recommend feature engineering steps

### Outlier Detection
- Identify anomalies in data
- Suggest outlier handling strategies
- Generate outlier reports

### Data Profiling
- Detect data types with higher accuracy
- Identify categorical vs. numeric features
- Generate comprehensive data quality reports

## 📝 Configuration

### CSV Reading Options

The tool can be extended with additional parameters:

```python
@mcp.tool()
def dataset_analyze(
    path: str,
    workspace_id: str,
    agent_id: str,
    session_id: str,
    target_column: str | None = None,
    sample_size: int | None = None,
    encoding: str = "utf-8",  # Add encoding support
    sep: str = ",",  # Add custom delimiter
):
    """..."""
```

### Memory Management

For very large datasets:
1. Use `sample_size` parameter
2. Process in chunks
3. Use `dtypes` parameter to specify data types upfront

## 🔧 Troubleshooting

### Issue: "Dataset not found"
- Verify the file exists in your workspace
- Check the path is relative to workspace root
- Verify workspace_id, agent_id, session_id are correct

### Issue: "Only CSV files are supported"
- Ensure file has `.csv` extension
- Convert other formats to CSV first

### Issue: "CSV parsing error"
- Check CSV format is valid
- Verify encoding (default: UTF-8)
- Ensure proper column separation

### Issue: Out of Memory
- Use `sample_size` parameter
- Reduce number of rows analyzed
- Increase system memory

## 📚 Integration with Aden

The tool integrates with Aden's MCP framework by:

1. **Security Sandboxing**: Uses `get_secure_path()` for file access control
2. **Tool Registration**: Follows Aden's `register_tools()` pattern
3. **FastMCP Integration**: Uses FastMCP decorator pattern
4. **Error Handling**: Returns structured error responses

## 📞 Support

For issues or questions:
1. Check the troubleshooting section
2. Review example usage
3. Consult Aden documentation
4. Open an issue on the repository

## 📄 License

This tool is part of the Aden MCP Framework and follows the same license.
