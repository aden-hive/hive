"""
Payroll Analysis Tool
Analyzes total payroll costs by department and identifies highest-paid employee
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
SERVER = os.getenv('MSSQL_SERVER', r'MONSTER\MSSQLSERVERR')
DATABASE = os.getenv('MSSQL_DATABASE', 'AdenTestDB')
USERNAME = os.getenv('MSSQL_USERNAME')
PASSWORD = os.getenv('MSSQL_PASSWORD')


def main():
    """Main analysis function."""
    connection = None

    try:
        print("=" * 80)
        print("  COMPANY PAYROLL ANALYSIS")
        print("=" * 80)
        print(f"Server: {SERVER}")
        print(f"Database: {DATABASE}")
        print()

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

        print("Connecting to database...")
        connection = pyodbc.connect(connection_string)
        cursor = connection.cursor()
        print("✓ Connection successful!")
        print()

        # Analysis 1: Total Payroll by Department
        print("=" * 80)
        print("  TOTAL SALARY COSTS BY DEPARTMENT")
        print("=" * 80)

        payroll_query = """
        SELECT
            d.name AS department_name,
            COUNT(e.employee_id) AS employee_count,
            SUM(e.salary) AS total_salary_cost,
            AVG(e.salary) AS avg_salary
        FROM Departments d
        LEFT JOIN Employees e ON d.department_id = e.department_id
        GROUP BY d.name
        ORDER BY total_salary_cost DESC
        """

        cursor.execute(payroll_query)

        print(f"\n{'Department':<25} {'Employees':<12} {'Total Salary Cost':<20} {'Avg Salary':<15}")
        print("-" * 80)

        total_company_payroll = 0
        total_employees = 0

        for row in cursor:
            dept_name = row[0]
            emp_count = row[1]
            total_salary = row[2] if row[2] else 0
            avg_salary = row[3] if row[3] else 0

            total_company_payroll += total_salary
            total_employees += emp_count

            total_salary_str = f"${total_salary:,.2f}"
            avg_salary_str = f"${avg_salary:,.2f}" if avg_salary > 0 else "N/A"

            print(f"{dept_name:<25} {emp_count:<12} {total_salary_str:<20} {avg_salary_str:<15}")

        print("-" * 80)
        print(f"{'TOTAL COMPANY':<25} {total_employees:<12} ${total_company_payroll:,.2f}")
        print("-" * 80)
        print()

        # Analysis 2: Highest Paid Employee
        print("=" * 80)
        print("  HIGHEST PAID EMPLOYEE")
        print("=" * 80)

        highest_paid_query = """
        SELECT TOP 1
            e.employee_id,
            e.first_name + ' ' + e.last_name AS full_name,
            e.email,
            e.salary,
            d.name AS department_name
        FROM Employees e
        INNER JOIN Departments d ON e.department_id = d.department_id
        ORDER BY e.salary DESC
        """

        cursor.execute(highest_paid_query)
        top_employee = cursor.fetchone()

        if top_employee:
            print(f"\n{'Field':<20} {'Value':<50}")
            print("-" * 80)
            print(f"{'Employee ID':<20} {top_employee[0]}")
            print(f"{'Name':<20} {top_employee[1]}")
            print(f"{'Email':<20} {top_employee[2]}")
            print(f"{'Department':<20} {top_employee[4]}")
            print(f"{'Salary':<20} ${top_employee[3]:,.2f}")
            print("-" * 80)
        else:
            print("\nNo employees found in the database.")

        print()

        # Additional Analysis: Top 5 Highest Paid Employees
        print("=" * 80)
        print("  TOP 5 HIGHEST PAID EMPLOYEES")
        print("=" * 80)

        top_5_query = """
        SELECT TOP 5
            e.first_name + ' ' + e.last_name AS full_name,
            d.name AS department_name,
            e.salary
        FROM Employees e
        INNER JOIN Departments d ON e.department_id = d.department_id
        ORDER BY e.salary DESC
        """

        cursor.execute(top_5_query)

        print(f"\n{'Rank':<6} {'Name':<30} {'Department':<25} {'Salary':<15}")
        print("-" * 80)

        rank = 1
        for row in cursor:
            full_name = row[0]
            dept_name = row[1]
            salary = row[2]

            print(f"{rank:<6} {full_name:<30} {dept_name:<25} ${salary:,.2f}")
            rank += 1

        print("-" * 80)
        print()

        # Summary
        print("=" * 80)
        print("  ANALYSIS SUMMARY")
        print("=" * 80)
        print(f"✓ Total Employees: {total_employees}")
        print(f"✓ Total Company Payroll: ${total_company_payroll:,.2f}")
        print(f"✓ Average Employee Salary: ${total_company_payroll / total_employees:,.2f}" if total_employees > 0 else "N/A")
        print("=" * 80)
        print("\nPayroll analysis completed successfully!")

    except pyodbc.Error as e:
        print("\n[ERROR] Database operation failed!")
        print(f"Error detail: {str(e)}")
        print()
        print("Possible solutions:")
        print("1. Ensure SQL Server is running")
        print("2. Verify database access permissions")
        print("3. Check connection string configuration")

    except Exception as e:
        print(f"\n[ERROR] Unexpected error: {str(e)}")

    finally:
        if connection:
            connection.close()
            print("\nConnection closed.")


if __name__ == "__main__":
    main()
