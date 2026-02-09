"""
Grant Permissions to AdenTestDB

This script grants the necessary permissions to the 'sa' user to access AdenTE testDB.
"""

import pyodbc

SERVER = r'MONSTER\MSSQLSERVERR'
USERNAME = 'sa'
PASSWORD = '622622aA.'


def grant_permissions():
    """Grant permissions to the database."""
    connection = None

    try:
        # Connect to AdenTestDB
        connection_string = (
            f'DRIVER={{ODBC Driver 17 for SQL Server}};'
            f'SERVER={SERVER};'
            f'DATABASE=AdenTestDB;'
            f'UID={USERNAME};'
            f'PWD={PASSWORD};'
            f'TrustServerCertificate=yes;'
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

    except pyodbc.Error as e:
        # If we can't connect, try connecting to master and creating user
        try:
            connection_string = (
                f'DRIVER={{ODBC Driver 17 for SQL Server}};'
                f'SERVER={SERVER};'
                f'DATABASE=master;'
                f'UID={USERNAME};'
                f'PWD={PASSWORD};'
                f'TrustServerCertificate=yes;'
            )

            print("Attempting to grant permissions via master database...")
            connection = pyodbc.connect(connection_string)
            cursor = connection.cursor()

            # Create login if not exists
            try:
                cursor.execute(f"""
                IF NOT EXISTS (SELECT * FROM sys.server_principals WHERE name = 'sa')
                BEGIN
                    CREATE LOGIN sa WITH PASSWORD = '{PASSWORD}'
                END
                """)
            except:
                pass

            # Switch to AdenTestDB and grant permissions
            cursor.execute("USE AdenTestDB")

            # Create user if not exists
            try:
                cursor.execute("""
                IF NOT EXISTS (SELECT * FROM sys.database_principals WHERE name = 'sa')
                BEGIN
                    CREATE USER sa FOR LOGIN sa
                END
                """)
                print("[OK] Created database user")
            except:
                pass

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
