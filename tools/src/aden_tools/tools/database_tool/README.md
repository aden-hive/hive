# Database Tool

A toolkit for querying SQLite databases within the Hive framework. This tool is designed with security in mind, enforcing read-only access and restricting queries to `SELECT` statements only.

## Tools Included

### `db_query`
Executes a read-only SQL query against a `.db` or `.sqlite` file.
- **Security:** Enforces `mode=ro` and blocks non-SELECT queries.
- **Safety:** Implements row limits to prevent context window overflow.

### `db_info`
Retrieves the database schema, including all table names and their respective column names/types. Useful for agents to "explore" a database before querying.

## Usage Example

```python
# The agent can call the tool like this:
db_query(path="data/business.db", query="SELECT * FROM users WHERE status='active'")