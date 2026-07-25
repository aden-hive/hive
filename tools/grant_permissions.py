"""
Grant Permissions to AdenTestDB

This script grants the necessary permissions to the 'sa' user to access AdenTE testDB.
"""

import os

import pyodbc

SERVER = os.getenv("MSSQL_SERVER", r"MONSTER\MSSQLSERVERR")
USERNAME = os.getenv("MSSQL_USERNAME", "sa")
PASSWORD = os.getenv("MSSQL_PASSWORD", "")
if not PASSWORD:
    raise SystemExit("ERROR: MSSQL_PASSWORD environment variable is required. "
                     "Set it before running this script.")


def grant_permissions():
    """Grant permissions to the database."""
    connection = None

    try:
        # Connect to AdenTestDB
        connection_string = (
            f"DRIVER={{ODBC Driver 17 for SQL Server}};"
            f"SERVER={SERVER};"
            f"DATABASE=AdenTestDB;"
            f"UID={USERNAME};"
            f"PWD={PASSWORD};"
            f"TrustServerCertificate=yes;"
        )

        print("=" * 70)
        print("Granting Permissions to AdenTestDB")
        print("=" * 70)
        print(f"Server: {SERVER}")
        print()

        print("Connecting to database...")
        connection = pyodbc.connect(connection_string)
        cursor = connection.cursor()

        print("[OK] Connected successfully!")
        print()

        # Grant permissions
        print("Granting permissions...")

        try:
            cursor.execute("GRANT SELECT, INSERT, UPDATE, DELETE ON SCHEMA::dbo TO sa")
            print("[OK] Granted schema permissions to sa")
        except pyodbc.Error as e:
            print(f"Note: {str(e)}")

        connection.commit()

        print()
        print("=" * 70)
        print("[SUCCESS] Permissions granted!")
        print("=" * 70)
        print()
        print("You can now run: python test_mssql_connection.py")

        return True

    except pyodbc.Error:
        # If we can't connect, try connecting to master and creating user
        try:
            connection_string = (
                f"DRIVER={{ODBC Driver 17 for SQL Server}};"
                f"SERVER={SERVER};"
                f"DATABASE=master;"
                f"UID={USERNAME};"
                f"PWD={PASSWORD};"
                f"TrustServerCertificate=yes;"
            )

            print("Attempting to grant permissions via master database...")
            connection = pyodbc.connect(connection_string)
            cursor = connection.cursor()

            # Create login if not exists
            try:
                cursor.execute("""
                IF NOT EXISTS (SELECT * FROM sys.server_principals WHERE name = ?)
                BEGIN
                    CREATE LOGIN ? WITH PASSWORD = ?
                END
                """, (USERNAME, USERNAME, PASSWORD))
            except pyodbc.Error as e:
                # Login might already exist, log but continue
                print(f"Note (login may already exist): {e}")

            # Switch to AdenTestDB and grant permissions
            cursor.execute("USE AdenTestDB")

            # Create user if not exists
            try:
                cursor.execute("""
                IF NOT EXISTS (SELECT * FROM sys.database_principals WHERE name = ?)
                BEGIN
                    CREATE USER ? FOR LOGIN ?
                END
                """, (USERNAME, USERNAME, USERNAME))
                print("[OK] Created database user")
            except pyodbc.Error as e:
                # User might already exist, log but continue
                print(f"Note (user may already exist): {e}")

            # Grant permissions
            cursor.execute("ALTER ROLE db_datareader ADD MEMBER sa")
            cursor.execute("ALTER ROLE db_datawriter ADD MEMBER sa")

            connection.commit()

            print("[OK] Permissions granted successfully!")
            return True

        except Exception as inner_e:
            print("\n[ERROR] Could not grant permissions!")
            print(f"Error: {str(inner_e)}")
            print()
            print("The database was created successfully, but there's a permission issue.")
            print("Please run this SQL command in SQL Server Management Studio:")
            print()
            print("USE AdenTestDB;")
            print("GO")
            print("ALTER ROLE db_datareader ADD MEMBER sa;")
            print("ALTER ROLE db_datawriter ADD MEMBER sa;")
            print("GO")
            return False

    finally:
        if connection:
            connection.close()
            print("\nConnection closed.")


if __name__ == "__main__":
    grant_permissions()
