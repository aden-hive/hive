"""
Query Average Salary by Department
"""

import os
import io
import sys

import pyodbc
from dotenv import load_dotenv

# Force UTF-8 encoding for console output
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8')

# Load environment variables from .env file
load_dotenv()

# Database connection settings (from environment variables)
SERVER = os.getenv('MSSQL_SERVER', r'MONSTER\\MSSQLSERVERR')
DATABASE = os.getenv('MSSQL_DATABASE', 'AdenTestDB')
USERNAME = os.getenv('MSSQL_USERNAME')
PASSWORD = os.getenv('MSSQL_PASSWORD')


def main():
    """Query and display average salary by department."""
    connection = None

    try:
        # Connect to database
        if USERNAME and PASSWORD:
            # SQL Server Authentication
            connection_string = (
                f'DRIVER={{ODBC Driver 17 for SQL Server}};'
                f'SERVER={SERVER};'
                f'DATABASE={DATABASE};'
                f'UID={USERNAME};'
                f'PWD={PASSWORD};'
            )
        else:
            # Windows Authentication
            connection_string = (
                f'DRIVER={{ODBC Driver 17 for SQL Server}};'
                f'SERVER={SERVER};'
                f'DATABASE={DATABASE};'
                f'Trusted_Connection=yes;'
            )

        connection = pyodbc.connect(connection_string)
        cursor = connection.cursor()

        # Query to get average salary by department, sorted by average salary descending
        query = """
        SELECT
            d.name AS department,
            AVG(e.salary) AS avg_salary,
            COUNT(e.employee_id) AS emp_count
        FROM Departments d
        LEFT JOIN Employees e ON d.department_id = e.department_id
        WHERE e.salary IS NOT NULL
        GROUP BY d.name
        ORDER BY avg_salary DESC
        """

        cursor.execute(query)
        results = cursor.fetchall()

        if not results:
            print("No salary data found.")
            return

        # Get the highest average salary for highlighting
        highest_avg = results[0][1] if results else 0

        print("=" * 80)
        print("  AVERAGE SALARY BY DEPARTMENT (Sorted Highest to Lowest)")
        print("=" * 80)
        print()
        print(f"{'Rank':<6} {'Department':<25} {'Avg Salary':<20} {'Employees':<12}")
        print("-" * 80)

        for idx, row in enumerate(results, 1):
            department = row[0]
            avg_salary = row[1]
            emp_count = row[2]

            avg_salary_str = f"${avg_salary:,.2f}"

            # Highlight the department with the highest average
            if avg_salary == highest_avg:
                # Use special formatting for the highest
                print(f"{'>>> ' + str(idx):<6} {department:<25} {avg_salary_str:<20} {emp_count:<12} ⭐ HIGHEST")
            else:
                print(f"{idx:<6} {department:<25} {avg_salary_str:<20} {emp_count:<12}")

        print("-" * 80)
        print()
        print(f"📊 Summary:")
        print(f"   • Total departments with employees: {len(results)}")
        print(f"   • Highest average salary: ${highest_avg:,.2f} ({results[0][0]})")
        print(f"   • Lowest average salary: ${results[-1][1]:,.2f} ({results[-1][0]})")
        print("=" * 80)

    except pyodbc.Error as e:
        print(f"\n[ERROR] Database operation failed: {str(e)}")

    except Exception as e:
        print(f"\n[ERROR] Unexpected error: {str(e)}")

    finally:
        if connection:
            connection.close()


if __name__ == "__main__":
    main()
