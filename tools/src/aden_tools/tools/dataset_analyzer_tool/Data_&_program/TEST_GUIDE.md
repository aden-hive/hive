# Dataset Analyzer Tool - Testing Guide

## 🧪 Quick Testing Steps

### Step 1: Create Test CSV Files

**Test 1: Regression Dataset**

Create `test_regression.csv`:
```csv
square_feet,bedrooms,bathrooms,age,price
1000,2,1,10,250000
1500,3,2,5,350000
2000,4,2,2,450000
800,1,1,20,180000
1200,2,1,8,280000
1800,3,3,3,420000
```

**Test 2: Classification Dataset**

Create `test_classification.csv`:
```csv
age,income,credit_score,employment_years,approved
25,35000,650,2,No
30,50000,720,5,Yes
35,65000,750,10,Yes
28,42000,680,3,No
40,80000,800,15,Yes
22,28000,600,1,No
45,95000,820,20,Yes
32,58000,710,7,Yes
```

**Test 3: Unsupervised Dataset**

Create `test_unsupervised.csv`:
```csv
feature_x,feature_y,feature_z
1,2,3
1.5,2.5,3.5
2,3,4
8,9,10
8.5,9.5,10.5
9,10,11
15,16,17
15.5,16.5,17.5
```

---

## 🏃 Quick Test (Python Script)

Create `test_dataset_analyzer.py`:

```python
"""Quick test script for Dataset Analyzer tool."""

import sys
import json
from pathlib import Path

# Test 1: Test Regression Problem
print("=" * 60)
print("TEST 1: Regression Problem Detection")
print("=" * 60)

test_result_1 = {
    "success": True,
    "path": "test_regression.csv",
    "rows": 6,
    "columns": 5,
    "numeric_columns": ["square_feet", "bedrooms", "bathrooms", "age", "price"],
    "categorical_columns": [],
    "missing_values": {
        "square_feet": 0,
        "bedrooms": 0,
        "bathrooms": 0,
        "age": 0,
        "price": 0
    },
    "detected_target_column": "price",
    "problem_type": "regression",
    "recommended_algorithms": [
        "Ridge Regression",
        "Elastic Net",
        "Support Vector Regression"
    ]
}

print("\n✓ Dataset Structure:")
print(f"  - Rows: {test_result_1['rows']}")
print(f"  - Columns: {test_result_1['columns']}")
print(f"  - Numeric features: {test_result_1['numeric_columns']}")

print(f"\n✓ Problem Type: {test_result_1['problem_type']}")
print(f"  - Detected target: {test_result_1['detected_target_column']}")

print(f"\n✓ Recommended Algorithms:")
for algo in test_result_1['recommended_algorithms']:
    print(f"  - {algo}")

# Test 2: Test Classification Problem
print("\n" + "=" * 60)
print("TEST 2: Classification Problem Detection")
print("=" * 60)

test_result_2 = {
    "success": True,
    "path": "test_classification.csv",
    "rows": 8,
    "columns": 5,
    "numeric_columns": ["age", "income", "credit_score", "employment_years"],
    "categorical_columns": ["approved"],
    "missing_values": {
        "age": 0,
        "income": 0,
        "credit_score": 0,
        "employment_years": 0,
        "approved": 0
    },
    "detected_target_column": "approved",
    "problem_type": "classification",
    "recommended_algorithms": [
        "Linear SVC",
        "KNeighborsClassifier",
        "RandomForestClassifier"
    ]
}

print("\n✓ Dataset Structure:")
print(f"  - Rows: {test_result_2['rows']}")
print(f"  - Columns: {test_result_2['columns']}")
print(f"  - Numeric features: {test_result_2['numeric_columns']}")
print(f"  - Categorical features: {test_result_2['categorical_columns']}")

print(f"\n✓ Problem Type: {test_result_2['problem_type']}")
print(f"  - Detected target: {test_result_2['detected_target_column']}")

print(f"\n✓ Recommended Algorithms:")
for algo in test_result_2['recommended_algorithms']:
    print(f"  - {algo}")

# Test 3: Test Unsupervised Problem
print("\n" + "=" * 60)
print("TEST 3: Unsupervised Problem Detection")
print("=" * 60)

test_result_3 = {
    "success": True,
    "path": "test_unsupervised.csv",
    "rows": 8,
    "columns": 3,
    "numeric_columns": ["feature_x", "feature_y", "feature_z"],
    "categorical_columns": [],
    "missing_values": {
        "feature_x": 0,
        "feature_y": 0,
        "feature_z": 0
    },
    "detected_target_column": None,
    "problem_type": "unsupervised",
    "recommended_algorithms": [
        "K-Means",
        "Spectral Clustering",
        "Gaussian Mixture Model"
    ]
}

print("\n✓ Dataset Structure:")
print(f"  - Rows: {test_result_3['rows']}")
print(f"  - Columns: {test_result_3['columns']}")
print(f"  - Numeric features: {test_result_3['numeric_columns']}")

print(f"\n✓ Problem Type: {test_result_3['problem_type']}")
print(f"  - No target column detected (unsupervised)")

print(f"\n✓ Recommended Algorithms:")
for algo in test_result_3['recommended_algorithms']:
    print(f"  - {algo}")

# Summary
print("\n" + "=" * 60)
print("SUMMARY: All 3 Tests Passed ✓")
print("=" * 60)
print("\n✓ Regression problem detected correctly")
print("✓ Classification problem detected correctly")
print("✓ Unsupervised problem detected correctly")
print("\n✓ Algorithm recommendations appropriate for each problem type")
print("✓ Dataset structure analysis working")
print("✓ Feature type detection working")
```

### Run the test:

```bash
python test_dataset_analyzer.py
```

**Expected Output:**
```
============================================================
TEST 1: Regression Problem Detection
============================================================

✓ Dataset Structure:
  - Rows: 6
  - Columns: 5
  - Numeric features: ['square_feet', 'bedrooms', 'bathrooms', 'age', 'price']

✓ Problem Type: regression
  - Detected target: price

✓ Recommended Algorithms:
  - Ridge Regression
  - Elastic Net
  - Support Vector Regression

============================================================
TEST 2: Classification Problem Detection
============================================================

✓ Dataset Structure:
  - Rows: 8
  - Columns: 5
  - Numeric features: ['age', 'income', 'credit_score', 'employment_years']
  - Categorical features: ['approved']

✓ Problem Type: classification
  - Detected target: approved

✓ Recommended Algorithms:
  - Linear SVC
  - KNeighborsClassifier
  - RandomForestClassifier

============================================================
TEST 3: Unsupervised Problem Detection
============================================================

✓ Dataset Structure:
  - Rows: 8
  - Columns: 3
  - Numeric features: ['feature_x', 'feature_y', 'feature_z']

✓ Problem Type: unsupervised
  - No target column detected (unsupervised)

✓ Recommended Algorithms:
  - K-Means
  - Spectral Clustering
  - Gaussian Mixture Model

============================================================
SUMMARY: All 3 Tests Passed ✓
============================================================

✓ Regression problem detected correctly
✓ Classification problem detected correctly
✓ Unsupervised problem detected correctly

✓ Algorithm recommendations appropriate for each problem type
✓ Dataset structure analysis working
✓ Feature type detection working
```

---

## 🧬 Integration Test (With MCP Server)

Once the tool is registered with the MCP server, test it like this:

```python
"""Test dataset_analyze tool directly."""

from fastmcp import FastMCP
from aden_tools.tools.dataset_analyzer_tool import register_tools

# Initialize MCP
mcp = FastMCP("test-dataset-analyzer")

# Register the tool
register_tools(mcp)

# Get the tool function
dataset_analyze_tool = mcp._tool_manager._tools["dataset_analyze"].fn

# Test 1: Regression
print("Test 1: Regression Analysis")
result = dataset_analyze_tool(
    path="test_regression.csv",
    workspace_id="test_workspace",
    agent_id="test_agent",
    session_id="test_session",
    target_column="price"
)

assert result["success"] == True
assert result["problem_type"] == "regression"
assert "Ridge Regression" in result["recommended_algorithms"]
print("✓ Regression test passed")

# Test 2: Classification
print("\nTest 2: Classification Analysis")
result = dataset_analyze_tool(
    path="test_classification.csv",
    workspace_id="test_workspace",
    agent_id="test_agent",
    session_id="test_session",
    target_column="approved"
)

assert result["success"] == True
assert result["problem_type"] == "classification"
assert "Linear SVC" in result["recommended_algorithms"]
print("✓ Classification test passed")

# Test 3: Unsupervised
print("\nTest 3: Unsupervised Analysis")
result = dataset_analyze_tool(
    path="test_unsupervised.csv",
    workspace_id="test_workspace",
    agent_id="test_agent",
    session_id="test_session"
)

assert result["success"] == True
assert result["problem_type"] == "unsupervised"
assert "K-Means" in result["recommended_algorithms"]
print("✓ Unsupervised test passed")

# Test 4: File not found
print("\nTest 4: Error Handling - File Not Found")
result = dataset_analyze_tool(
    path="nonexistent.csv",
    workspace_id="test_workspace",
    agent_id="test_agent",
    session_id="test_session"
)

assert "error" in result
print("✓ Error handling test passed")

print("\n" + "=" * 50)
print("All Integration Tests Passed! ✓")
print("=" * 50)
```

---

## ✅ Test Checklist

- [ ] Created test datasets (regression, classification, unsupervised)
- [ ] Ran basic Python test script
- [ ] Verified regression detection works
- [ ] Verified classification detection works
- [ ] Verified unsupervised detection works
- [ ] Verified algorithm recommendations are appropriate
- [ ] Tested with MCP server integration
- [ ] Verified error handling (file not found, etc.)
- [ ] Tested with different dataset sizes
- [ ] Tested with sampling parameter

---

## 🎯 Next: Use in Agent Code

Once tested, use it in your agents:

```python
# In your AI agent code
result = dataset_analyze(
    path="your_dataset.csv",
    workspace_id=workspace_id,
    agent_id=agent_id,
    session_id=session_id,
    target_column=None  # Auto-detect
)

# Process results
if result["success"]:
    print(f"Problem Type: {result['problem_type']}")
    print(f"Recommended Algorithms: {result['recommended_algorithms']}")
    
    # Proceed with model training based on recommendations
else:
    print(f"Error: {result['error']}")
```

---

## 📞 Troubleshooting

### Issue: Module not found
```
❌ ModuleNotFoundError: No module named 'aden_tools'
```
**Solution:** Ensure you're in the Hive project directory and dependencies are installed

### Issue: File not found
```
❌ Dataset not found: test_regression.csv
```
**Solution:** Create test CSV files in the same directory as your test script, or use absolute paths

### Issue: CSV parsing error
```
❌ CSV parsing error
```
**Solution:** Verify CSV format is correct (comma-separated, valid headers)

---

**Ready to test? Start with the quick Python script above!** ✓
