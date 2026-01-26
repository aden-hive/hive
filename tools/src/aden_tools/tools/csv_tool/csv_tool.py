"""
CSV Tool - Analyze and inspect CSV files.
"""
import csv
import os
import random
from typing import Optional, List, Dict, Any
from fastmcp import FastMCP

def register_tools(mcp: FastMCP, credentials=None) -> None:
    """Register CSV tools with the MCP server."""

    @mcp.tool()
    def read_csv_head(filepath: str, n_rows: int = 5) -> Dict[str, Any]:
        """
        Read the first N rows of a CSV file.
        
        Args:
            filepath: Absolute path to the CSV file
            n_rows: Number of rows to read (default 5)
        """
        if not os.path.exists(filepath):
            return {"error": f"File not found: {filepath}"}
            
        try:
            with open(filepath, 'r', encoding='utf-8', errors='replace') as f:
                reader = csv.reader(f)
                try:
                    headers = next(reader)
                except StopIteration:
                    return {"error": "CSV file is empty"}
                
                rows = []
                for i, row in enumerate(reader):
                    if i >= n_rows:
                        break
                    rows.append(row)
                    
            return {
                "filepath": filepath,
                "headers": headers,
                "rows": rows,
                "row_count_returned": len(rows)
            }
        except Exception as e:
            return {"error": str(e)}

    @mcp.tool()
    def get_csv_info(filepath: str) -> Dict[str, Any]:
        """
        Get metadata about a CSV file (headers, row count, size).
        
        Args:
            filepath: Absolute path to the CSV file
        """
        if not os.path.exists(filepath):
            return {"error": f"File not found: {filepath}"}
            
        try:
            file_size = os.path.getsize(filepath)
            
            with open(filepath, 'r', encoding='utf-8', errors='replace') as f:
                reader = csv.reader(f)
                try:
                    headers = next(reader)
                except StopIteration:
                    return {"error": "CSV file is empty"}
                
                row_count = sum(1 for _ in reader)
                
            return {
                "filepath": filepath,
                "file_size_bytes": file_size,
                "headers": headers,
                "column_count": len(headers),
                "row_count": row_count
            }
        except Exception as e:
            return {"error": str(e)}

    @mcp.tool()
    def sample_csv(filepath: str, n_samples: int = 10) -> Dict[str, Any]:
        """
        Randomly sample rows from a CSV file.
        
        Args:
            filepath: Absolute path to the CSV file
            n_samples: Number of random samples to return
        """
        if not os.path.exists(filepath):
            return {"error": f"File not found: {filepath}"}
            
        try:
            # First pass: count rows
            with open(filepath, 'r', encoding='utf-8', errors='replace') as f:
                reader = csv.reader(f)
                try:
                    headers = next(reader)
                except StopIteration:
                    return {"error": "CSV file is empty"}
                
                rows = list(reader)
                total_rows = len(rows)
                
            if total_rows == 0:
                return {"headers": headers, "samples": []}
                
            # Sample
            sample_indices = random.sample(range(total_rows), min(n_samples, total_rows))
            samples = [rows[i] for i in sorted(sample_indices)]
            
            return {
                "filepath": filepath,
                "headers": headers,
                "total_rows": total_rows,
                "samples": samples
            }
        except Exception as e:
            return {"error": str(e)}
