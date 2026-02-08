import re

FORBIDDEN_PATTERN = re.compile(
    r"\b(insert|update|delete|merge|upsert|create|alter|drop|truncate|grant|revoke|"
    r"call|execute|prepare|deallocate|vacuum|analyze)\b",
    re.IGNORECASE,
)


def validate_sql(sql: str) -> str:
    """
    Enforce SELECT-only, single-statement SQL.
    """
    sql = sql.strip()

    # Allow a single trailing semicolon
    if sql.endswith(";"):
        sql = sql[:-1]

    if ";" in sql:
        raise ValueError("Multiple statements are not allowed")

    if not sql.lower().startswith("select"):
        raise ValueError("Only SELECT queries are allowed")

    if FORBIDDEN_PATTERN.search(sql):
        raise ValueError("Forbidden SQL keyword detected")

    return sql
