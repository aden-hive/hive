"""
Query to find top 3 highest paid employees
"""

import os
import io
import sys
import pyodbc
from dotenv import load_dotenv

# Force UTF-8 encoding for console output
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8')

# Load environment variables
load_dotenv()

# Database connection settings
SERVER = os.getenv('MSSQL_SERVER', r'MONSTER\MSSQLSERVERR')
DATABASE = os.getenv('MSSQL_DATABASE', 'AdenTestDB')
USERNAME = os.getenv('MSSQL_USERNAME')
PASSWORD = os.getenv('MSSQL_PASSWORD')

def main():
    connection = None

    try:
        # Connect to database
        if USERNAME and PASSWORD:
            connection_string = (
                f'DRIVER={{ODBC Driver 17 for SQL Server}};'
                f'SERVER={SERVER};'
                f'DATABASE={DATABASE};'
                f'UID={USERNAME};'
                f'PWD={PASSWORD};'
            )
        else:
            connection_string = (
                f'DRIVER={{ODBC Driver 17 for SQL Server}};'
                f'SERVER={SERVER};'
                f'DATABASE={DATABASE};'
                f'Trusted_Connection=yes;'
            )

        connection = pyodbc.connect(connection_string)
        cursor = connection.cursor()

        # Query for top 3 highest paid employees
        query = """
        SELECT TOP 3
            e.first_name + ' ' + e.last_name AS full_name,
            e.email,
            d.name AS department,
            e.salary
        FROM Employees e
        INNER JOIN Departments d ON e.department_id = d.department_id
        ORDER BY e.salary DESC
        """

        cursor.execute(query)

        print("\n## 💰 Top 3 Highest Paid Employees\n")
        print("| Rank | Employee Name | Email | Department | Salary |")
        print("|------|---------------|-------|------------|--------|")

        rank = 1
        for row in cursor:
            name = row[0]
            email = row[1]
            department = row[2]
            salary = f"${row[3]:,.2f}"
            print(f"| {rank} | {name} | {email} | {department} | {salary} |")
            rank += 1

        print()

    except pyodbc.Error as e:
        print(f"\n[ERROR] Database operation failed: {str(e)}")
    except Exception as e:
        print(f"\n[ERROR] Unexpected error: {str(e)}")
    finally:
        if connection:
            connection.close()

if __name__ == "__main__":
    main()
