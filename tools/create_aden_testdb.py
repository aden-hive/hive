"""
Database Initialization Script Runner for AdenTestDB

This script executes the SQL initialization file to create the AdenTestDB database.
Make sure your SQL Server is running before executing this script.
"""

import os

import pyodbc
from dotenv import load_dotenv

# Load environment variables from .env
load_dotenv()

# Database connection settings (from environment variables)
SERVER = os.getenv('MSSQL_SERVER', r'MONSTER\MSSQLSERVERR')
USERNAME = os.getenv('MSSQL_USERNAME')
PASSWORD = os.getenv('MSSQL_PASSWORD')

# SQL file path
SQL_FILE = os.path.join(os.path.dirname(__file__), 'init_aden_testdb.sql')


def execute_sql_file():
    """Execute the SQL initialization file."""
    connection = None

    try:
        # Read SQL file
        if not os.path.exists(SQL_FILE):
            print(f"[ERROR] SQL file not found: {SQL_FILE}")
            return False

        with open(SQL_FILE, 'r', encoding='utf-8') as f:
            sql_script = f.read()

        print("=" * 70)
        print("AdenTestDB Database Initialization")
        print("=" * 70)
        print(f"Server: {SERVER}")
        print(f"SQL Script: {SQL_FILE}")
        print()

        # Connect to master database (to create new database)
        connection_string = (
            f'DRIVER={{ODBC Driver 17 for SQL Server}};'
            f'SERVER={SERVER};'
            f'DATABASE=master;'
            f'UID={USERNAME};'
            f'PWD={PASSWORD};'
        )

        print("Connecting to SQL Server...")
        connection = pyodbc.connect(connection_string)
        connection.autocommit = True  # Required for CREATE DATABASE
        cursor = connection.cursor()

        print("[OK] Connected successfully!")
        print()
        print("Executing SQL script...")
        print("-" * 70)

        # Split by GO statements and execute each batch
        batches = sql_script.split('\nGO\n')

        for i, batch in enumerate(batches, 1):
            batch = batch.strip()
            if batch and not batch.startswith('--'):
                try:
                    cursor.execute(batch)
                    # Print any messages from the server
                    while cursor.nextset():
                        pass
                except pyodbc.Error as e:
                    # Some statements might not return results, that's OK
                    if "No results" not in str(e):
                        print(f"Warning in batch {i}: {str(e)}")

        print("-" * 70)
        print()
        print("=" * 70)
        print("[SUCCESS] Database initialization completed successfully!")
        print("=" * 70)
        print()
        print("Next steps:")
        print("1. Run: python test_mssql_connection.py")
        print("2. Verify the relational schema and sample data")
        print()

        return True

    except pyodbc.Error as e:
        print()
        print("=" * 70)
        print("[ERROR] Database initialization failed!")
        print("=" * 70)
        print(f"Error detail: {str(e)}")
        print()
        print("Possible solutions:")
        print("1. Ensure SQL Server is running")
        print("2. Check server name, username, and password")
        print("3. Ensure you have permission to create databases")
        print("4. Verify ODBC Driver 17 for SQL Server is installed")
        print()
        return False

    except Exception as e:
        print(f"\n[ERROR] Unexpected error: {str(e)}")
        return False

    finally:
        if connection:
            connection.close()
            print("Connection closed.")


if __name__ == "__main__":
    success = execute_sql_file()
    exit(0 if success else 1)
