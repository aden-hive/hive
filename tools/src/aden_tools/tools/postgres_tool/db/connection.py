import os

import psycopg


def get_connection():
    """
    Return a connection to a PostgreSQL database.

    The connection parameters are obtained from environment variables:

    - PG_HOST: the hostname of the PostgreSQL server
    - PG_PORT: the port number of the PostgreSQL server
    - PG_DATABASE: the name of the database to connect to
    - PG_USER: the username to use for authentication
    - PG_PASSWORD: the password to use for authentication
    - PG_SSLMODE: the SSL mode to use for the connection.
    One of:
    - "disable"
    - "prefer"
    - "require"
    - "verify-ca"
    - "verify-full"

    If not specified, the connection is established without SSL.

    The returned connection object is a `psycopg2.extensions.connection` object.

    :rtype: psycopg2.extensions.connection
    """
    return psycopg.connect(
        host=os.getenv("PG_HOST"),
        port=int(os.getenv("PG_PORT", "5432")),
        dbname=os.getenv("PG_DATABASE"),
        user=os.getenv("PG_USER"),
        password=os.getenv("PG_PASSWORD"),
        sslmode=os.getenv("PG_SSLMODE", "disable"),
    )
