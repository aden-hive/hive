"""Dataset Analyzer Tool for Aden MCP Framework.

Analyzes CSV datasets and provides ML algorithm recommendations based on
dataset characteristics using scikit-learn cheat sheet logic.
"""

import os
import pandas as pd
import numpy as np

from fastmcp import FastMCP
from ..file_system_toolkits.security import get_secure_path


def register_tools(mcp: FastMCP) -> None:
    """Register dataset analyzer tools with the MCP server.
    
    Args:
        mcp: FastMCP instance to register tools with
    """

    @mcp.tool()
    def dataset_analyze(
        path: str,
        workspace_id: str,
        agent_id: str,
        session_id: str,
        target_column: str | None = None,
        sample_size: int | None = None,
    ) -> dict:
        """
        Analyze a CSV dataset and recommend machine learning algorithms.

        This tool provides comprehensive dataset analysis including statistical
        summaries, feature analysis, correlation detection, and ML algorithm
        recommendations based on the dataset characteristics.

        Args:
            path: Path to CSV dataset (relative to workspace)
            workspace_id: Workspace identifier for security sandboxing
            agent_id: Agent identifier for security sandboxing
            session_id: Session identifier for security sandboxing
            target_column: Optional target column name for supervised learning
            sample_size: Optional number of rows to sample for faster analysis

        Returns:
            dict containing dataset insights and ML recommendations with keys:
                - success (bool): Whether analysis succeeded
                - path (str): Path to analyzed dataset
                - rows (int): Number of rows in dataset
                - columns (int): Number of columns in dataset
                - numeric_columns (list): Names of numeric feature columns
                - categorical_columns (list): Names of categorical feature columns
                - missing_values (dict): Missing value counts per column
                - summary_statistics (dict): Statistical summaries (mean, std, etc.)
                - top_correlations (dict): Top 3 correlations per numeric column
                - detected_target_column (str): Detected or provided target column
                - problem_type (str): 'classification', 'regression', or 'unsupervised'
                - recommended_algorithms (list): List of recommended ML algorithms
                - error (str): Error message if analysis failed
        """

        try:
            # Validate and get secure path through sandbox
            secure_path = get_secure_path(path, workspace_id, agent_id, session_id)

            # Check file existence
            if not os.path.exists(secure_path):
                return {"error": f"Dataset not found: {path}"}

            # Validate file format
            if not path.lower().endswith(".csv"):
                return {"error": "Only CSV files are supported"}

            # Load dataset
            df = pd.read_csv(secure_path)

            # Check if dataset is empty
            if df.empty:
                return {"error": "Dataset is empty"}

            # Apply sampling if requested
            if sample_size and sample_size < len(df):
                df = df.sample(n=sample_size, random_state=42)

            # Basic dataset information
            rows = len(df)
            columns = len(df.columns)

            # Feature type detection
            numeric_columns = df.select_dtypes(include=np.number).columns.tolist()
            categorical_columns = df.select_dtypes(exclude=np.number).columns.tolist()

            # Missing values analysis
            missing_values = df.isnull().sum().to_dict()

            # Summary statistics for numeric columns
            summary_stats = {}
            if numeric_columns:
                summary_stats = df[numeric_columns].describe().to_dict()

            # Correlation analysis for numeric columns
            correlations = {}
            if len(numeric_columns) > 1:
                corr_matrix = df[numeric_columns].corr()

                # Get top 3 correlations for each column
                for col in corr_matrix.columns:
                    top_corr = (
                        corr_matrix[col]
                        .drop(labels=[col])
                        .abs()
                        .nlargest(3)
                        .to_dict()
                    )
                    correlations[col] = top_corr

            # Detect target column automatically if not provided
            detected_target = target_column

            if not detected_target:
                # Auto-detect: look for columns with low cardinality
                for col in df.columns:
                    if df[col].dtype == "object":
                        detected_target = col
                        break
                    elif df[col].nunique() < 20 and df[col].nunique() > 1:
                        detected_target = col
                        break

            # Determine ML problem type
            problem_type = "unsupervised"

            if detected_target:
                target_dtype = df[detected_target].dtype
                target_cardinality = df[detected_target].nunique()

                # Classification: categorical or few unique values
                if target_dtype == "object" or target_cardinality < 20:
                    problem_type = "classification"
                # Regression: many numeric values
                else:
                    problem_type = "regression"

            # Recommend algorithms based on problem type and dataset size
            recommended_algorithms = []

            if problem_type == "classification":
                # Classification recommendations based on dataset size
                if rows < 100000:
                    # For smaller datasets: use algorithms with better generalization
                    recommended_algorithms = [
                        "Linear SVC",
                        "KNeighborsClassifier",
                        "RandomForestClassifier",
                    ]
                else:
                    # For larger datasets: use scalable algorithms
                    recommended_algorithms = [
                        "SGDClassifier",
                        "NaiveBayes",
                        "GradientBoostingClassifier",
                    ]

            elif problem_type == "regression":
                # Regression recommendations based on dataset size
                if rows < 100000:
                    # For smaller datasets: use complex models
                    recommended_algorithms = [
                        "Ridge Regression",
                        "Elastic Net",
                        "Support Vector Regression",
                    ]
                else:
                    # For larger datasets: use scalable models
                    recommended_algorithms = [
                        "SGD Regressor",
                        "Random Forest Regressor",
                        "Gradient Boosting Regressor",
                    ]

            else:  # unsupervised
                # Clustering/dimensionality reduction recommendations
                if rows < 10000:
                    # For smaller datasets: use exact algorithms
                    recommended_algorithms = [
                        "K-Means",
                        "Spectral Clustering",
                        "Gaussian Mixture Model",
                    ]
                else:
                    # For larger datasets: use approximate algorithms
                    recommended_algorithms = [
                        "Mini-Batch K-Means",
                        "Principal Component Analysis",
                        "DBSCAN",
                    ]

            # Return comprehensive analysis results
            return {
                "success": True,
                "path": path,
                "rows": rows,
                "columns": columns,
                "numeric_columns": numeric_columns,
                "categorical_columns": categorical_columns,
                "missing_values": missing_values,
                "summary_statistics": summary_stats,
                "top_correlations": correlations,
                "detected_target_column": detected_target,
                "problem_type": problem_type,
                "recommended_algorithms": recommended_algorithms,
            }

        except FileNotFoundError:
            return {"error": f"Dataset file not found: {path}"}
        except pd.errors.ParserError as e:
            return {"error": f"CSV parsing error: {str(e)}"}
        except Exception as e:
            return {"error": f"Dataset analysis failed: {str(e)}"}
