"""
Test MSSQL Schema Discovery
Verifies that the mssql_get_schema functionality works correctly.
"""

import os
import sys
import io
from dotenv import load_dotenv
import pyodbc

# Force UTF-8 encoding for console output
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8')

# Load environment variables from .env file
load_dotenv()

# Database connection settings
SERVER = os.getenv('MSSQL_SERVER', r'MONSTER\MSSQLSERVERR')
DATABASE = os.getenv('MSSQL_DATABASE', 'AdenTestDB')
USERNAME = os.getenv('MSSQL_USERNAME')
PASSWORD = os.getenv('MSSQL_PASSWORD')


def get_connection():
    """Create and return a database connection."""
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

    return pyodbc.connect(connection_string, timeout=10)


def list_all_tables(cursor):
    """List all tables in the database."""
    cursor.execute("""
        SELECT TABLE_NAME
        FROM INFORMATION_SCHEMA.TABLES
        WHERE TABLE_TYPE = 'BASE TABLE'
        ORDER BY TABLE_NAME
    """)
    tables = [row[0] for row in cursor.fetchall()]
    return tables


def get_table_schema(cursor, table_name):
    """Get detailed schema for a specific table."""
    # Get columns with primary key information
    cursor.execute("""
        SELECT
            c.COLUMN_NAME,
            c.DATA_TYPE,
            c.CHARACTER_MAXIMUM_LENGTH,
            c.NUMERIC_PRECISION,
            c.NUMERIC_SCALE,
            c.IS_NULLABLE,
            CASE WHEN pk.COLUMN_NAME IS NOT NULL THEN 1 ELSE 0 END AS IS_PRIMARY_KEY
        FROM INFORMATION_SCHEMA.COLUMNS c
        LEFT JOIN (
            SELECT ku.COLUMN_NAME
            FROM INFORMATION_SCHEMA.TABLE_CONSTRAINTS tc
            JOIN INFORMATION_SCHEMA.KEY_COLUMN_USAGE ku
                ON tc.CONSTRAINT_NAME = ku.CONSTRAINT_NAME
            WHERE tc.CONSTRAINT_TYPE = 'PRIMARY KEY'
                AND tc.TABLE_NAME = ?
        ) pk ON c.COLUMN_NAME = pk.COLUMN_NAME
        WHERE c.TABLE_NAME = ?
        ORDER BY c.ORDINAL_POSITION
    """, table_name, table_name)

    columns = []
    for row in cursor.fetchall():
        col_type = row[1]

        # Add length/precision info
        if row[2]:  # CHARACTER_MAXIMUM_LENGTH
            col_type += f"({row[2]})"
        elif row[3]:  # NUMERIC_PRECISION
            if row[4]:  # NUMERIC_SCALE
                col_type += f"({row[3]},{row[4]})"
            else:
                col_type += f"({row[3]})"

        columns.append({
            "name": row[0],
            "type": col_type,
            "nullable": row[5] == "YES",
            "primary_key": bool(row[6]),
        })

    # Get foreign keys
    cursor.execute("""
        SELECT
            kcu.COLUMN_NAME,
            ccu.TABLE_NAME AS REFERENCED_TABLE,
            ccu.COLUMN_NAME AS REFERENCED_COLUMN
        FROM INFORMATION_SCHEMA.REFERENTIAL_CONSTRAINTS rc
        JOIN INFORMATION_SCHEMA.KEY_COLUMN_USAGE kcu
            ON rc.CONSTRAINT_NAME = kcu.CONSTRAINT_NAME
        JOIN INFORMATION_SCHEMA.CONSTRAINT_COLUMN_USAGE ccu
            ON rc.UNIQUE_CONSTRAINT_NAME = ccu.CONSTRAINT_NAME
        WHERE kcu.TABLE_NAME = ?
    """, table_name)

    foreign_keys = []
    for row in cursor.fetchall():
        foreign_keys.append({
            "column": row[0],
            "references_table": row[1],
            "references_column": row[2],
        })

    return {
        "table": table_name,
        "columns": columns,
        "foreign_keys": foreign_keys
    }


def print_table_schema(schema, is_last=False):
    """Pretty print table schema."""
    table_name = schema["table"]
    columns = schema["columns"]
    foreign_keys = schema["foreign_keys"]

    print(f"\n📋 Table: {table_name}")
    print("=" * 80)

    # Print columns
    print(f"\n  Columns ({len(columns)}):")
    print("  " + "-" * 76)
    print(f"  {'Column Name':<30} {'Type':<25} {'Nullable':<10} {'PK':<5}")
    print("  " + "-" * 76)

    for col in columns:
        pk_mark = "✓" if col["primary_key"] else ""
        nullable = "YES" if col["nullable"] else "NO"
        print(f"  {col['name']:<30} {col['type']:<25} {nullable:<10} {pk_mark:<5}")

    # Print foreign keys
    if foreign_keys:
        print(f"\n  Foreign Keys ({len(foreign_keys)}):")
        print("  " + "-" * 76)
        for fk in foreign_keys:
            print(f"  {fk['column']} → {fk['references_table']}({fk['references_column']})")
    else:
        print("\n  Foreign Keys: None")

    print()
    if not is_last:
        print("─" * 80)


def main():
    """Main test function."""
    try:
        print("=" * 80)
        print("  MSSQL SCHEMA DISCOVERY TEST")
        print("=" * 80)
        print(f"Server: {SERVER}")
        print(f"Database: {DATABASE}")
        print()

        # Connect to database
        print("Connecting to database...")
        connection = get_connection()
        cursor = connection.cursor()
        print("✓ Connected successfully!")
        print()

        # List all tables
        print("=" * 80)
        print("  DISCOVERING DATABASE SCHEMA")
        print("=" * 80)

        tables = list_all_tables(cursor)
        print(f"\n✓ Found {len(tables)} table(s) in the database:")
        for i, table in enumerate(tables, 1):
            print(f"  {i}. {table}")

        # Get detailed schema for each table
        print("\n" + "=" * 80)
        print("  DETAILED SCHEMA INFORMATION")
        print("=" * 80)

        for i, table in enumerate(tables):
            schema = get_table_schema(cursor, table)
            is_last = (i == len(tables) - 1)
            print_table_schema(schema, is_last)

        # Summary
        print("=" * 80)
        print("  SUMMARY")
        print("=" * 80)
        print(f"✓ Total Tables: {len(tables)}")

        total_columns = 0
        total_fks = 0
        for table in tables:
            schema = get_table_schema(cursor, table)
            total_columns += len(schema["columns"])
            total_fks += len(schema["foreign_keys"])

        print(f"✓ Total Columns: {total_columns}")
        print(f"✓ Total Foreign Keys: {total_fks}")
        print()
        print("✓ Schema discovery completed successfully!")
        print("=" * 80)

        connection.close()

    except pyodbc.Error as e:
        print("\n[ERROR] Database operation failed!")
        print(f"Error detail: {str(e)}")
        return 1

    except Exception as e:
        print(f"\n[ERROR] Unexpected error: {str(e)}")
        return 1

    return 0


if __name__ == "__main__":
    sys.exit(main())
