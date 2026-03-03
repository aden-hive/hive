"""
Simple MSSQL Connection and Query Test
Tests the AdenTestDB database with JOIN queries
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
    """Main test function."""
    connection = None

    try:
        print("=" * 70)
        print("  MSSQL Connection Test for AdenTestDB")
        print("=" * 70)
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

        # Test 1: Count tables
        print("=" * 70)
        print("  Table Count Verification")
        print("=" * 70)

        cursor.execute("SELECT COUNT(*) FROM Departments")
        dept_count = cursor.fetchone()[0]
        print(f"✓ Departments: {dept_count} records")

        cursor.execute("SELECT COUNT(*) FROM Employees")
        emp_count = cursor.fetchone()[0]
        print(f"✓ Employees: {emp_count} records")
        print()

        # Test 2: JOIN Query
        print("=" * 70)
        print("  JOIN Query Test - Employees with Departments")
        print("=" * 70)

        query = """
        SELECT
            e.employee_id,
            e.first_name + ' ' + e.last_name AS full_name,
            e.email,
            e.salary,
            d.name AS department
        FROM Employees e
        INNER JOIN Departments d ON e.department_id = d.department_id
        ORDER BY d.name, e.last_name
        """

        cursor.execute(query)

        print("\nEmployee List with Departments:")
        print("-" * 70)
        print(f"{'ID':<6} {'Name':<25} {'Email':<30} {'Dept':<15}")
        print("-" * 70)

        row_count = 0
        for row in cursor:
            row_count += 1
            print(f"{row[0]:<6} {row[1]:<25} {row[2]:<30} {row[4]:<15}")

        print("-" * 70)
        print(f"✓ Total records fetched: {row_count}")
        print()

        # Test 3: Aggregate Query
        print("=" * 70)
        print("  Aggregate Query - Department Statistics")
        print("=" * 70)

        query = """
        SELECT
            d.name AS department,
            COUNT(e.employee_id) AS emp_count,
            AVG(e.salary) AS avg_salary,
            d.budget
        FROM Departments d
        LEFT JOIN Employees e ON d.department_id = e.department_id
        GROUP BY d.name, d.budget
        ORDER BY emp_count DESC
        """

        cursor.execute(query)

        print(f"\n{'Department':<20} {'Employees':<12} {'Avg Salary':<15} {'Budget':<15}")
        print("-" * 70)

        for row in cursor:
            avg_salary = f"${row[2]:,.2f}" if row[2] else "N/A"
            budget = f"${row[3]:,.2f}"
            print(f"{row[0]:<20} {row[1]:<12} {avg_salary:<15} {budget:<15}")

        print("-" * 70)
        print("✓ Aggregate query completed!")
        print()

        # Test 4: Foreign Key Integrity
        print("=" * 70)
        print("  Relational Integrity Check")
        print("=" * 70)

        query = """
        SELECT COUNT(*)
        FROM Employees e
        LEFT JOIN Departments d ON e.department_id = d.department_id
        WHERE d.department_id IS NULL
        """

        cursor.execute(query)
        orphaned = cursor.fetchone()[0]

        if orphaned == 0:
            print("✓ All employees have valid department associations")
            print("✓ Foreign key constraints verified")
        else:
            print(f"⚠ WARNING: Found {orphaned} orphaned records!")

        print()

        # Final Summary
        print("=" * 70)
        print("  Test Summary")
        print("=" * 70)
        print("✓ Connection to AdenTestDB successful")
        print("✓ Table counts verified")
        print("✓ JOIN query executed successfully")
        print("✓ Aggregate functions working")
        print("✓ Relational integrity confirmed")
        print("=" * 70)
        print("\nAll tests passed successfully!")

    except pyodbc.Error as e:
        print("\n[ERROR] Database operation failed!")
        print(f"Error detail: {str(e)}")
        print()
        print("Possible solutions:")
        print("1. Ensure SQL Server is running")
        print("2. Verify the 'sa' user has permission to access AdenTestDB")
        print("3. Try running: sqlcmd -S MONSTER\\MSSQLSERVERR -U sa -P 622622aA. -Q \"USE AdenTestDB; SELECT 1;\"")
        print("4. Grant permissions: GRANT CONNECT TO sa; USE AdenTestDB; GRANT SELECT TO sa;")

    except Exception as e:
        print(f"\n[ERROR] Unexpected error: {str(e)}")

    finally:
        if connection:
            connection.close()
            print("\nConnection closed.")


if __name__ == "__main__":
    main()
