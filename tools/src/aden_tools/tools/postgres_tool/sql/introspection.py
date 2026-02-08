LIST_SCHEMAS_SQL = """
SELECT schema_name
FROM information_schema.schemata
ORDER BY schema_name
"""

LIST_TABLES_SQL = """
SELECT table_schema, table_name
FROM information_schema.tables
WHERE table_type = 'BASE TABLE'
"""

DESCRIBE_TABLE_SQL = """
SELECT
    column_name,
    data_type,
    is_nullable,
    column_default
FROM information_schema.columns
WHERE table_schema = %(schema)s
  AND table_name = %(table)s
ORDER BY ordinal_position
"""
