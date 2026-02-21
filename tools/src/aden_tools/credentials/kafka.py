"""
Kafka tool credentials.

Contains credentials for Apache Kafka event streaming integration.
"""

from .base import CredentialSpec

KAFKA_TOOLS = [
    "kafka_produce_message",
    "kafka_produce_batch",
    "kafka_flush",
    "kafka_subscribe",
    "kafka_consume_messages",
    "kafka_commit_offset",
    "kafka_seek",
    "kafka_unsubscribe",
    "kafka_create_topic",
    "kafka_delete_topic",
    "kafka_list_topics",
    "kafka_describe_topic",
    "kafka_list_consumer_groups",
    "kafka_describe_consumer_group",
    "kafka_delete_consumer_group",
    "kafka_get_broker_metadata",
    "kafka_get_offsets",
]

KAFKA_CREDENTIALS = {
    "kafka_bootstrap_servers": CredentialSpec(
        env_var="KAFKA_BOOTSTRAP_SERVERS",
        tools=KAFKA_TOOLS,
        required=True,
        startup_required=False,
        help_url="https://kafka.apache.org/documentation/#brokerconfigs",
        description="Comma-separated list of Kafka broker addresses (e.g., localhost:9092)",
        aden_supported=False,
        direct_api_key_supported=True,
        api_key_instructions="""To configure Kafka connection:

1. Local Development (no auth):
   KAFKA_BOOTSTRAP_SERVERS=localhost:9092

2. Confluent Cloud:
   KAFKA_BOOTSTRAP_SERVERS=pkc-xxxxx.us-east-1.aws.confluent.cloud:9092
   KAFKA_SASL_USERNAME=your-api-key
   KAFKA_SASL_PASSWORD=your-api-secret
   KAFKA_SECURITY_PROTOCOL=SASL_SSL

3. Self-hosted with SASL:
   KAFKA_BOOTSTRAP_SERVERS=broker1:9092,broker2:9092
   KAFKA_SASL_USERNAME=your-username
   KAFKA_SASL_PASSWORD=your-password
   KAFKA_SECURITY_PROTOCOL=SASL_PLAINTEXT

4. Self-hosted with SSL:
   KAFKA_BOOTSTRAP_SERVERS=broker1:9093,broker2:9093
   KAFKA_SSL_CA_LOCATION=/path/to/ca.pem
   KAFKA_SECURITY_PROTOCOL=SSL""",
        credential_id="kafka",
        credential_key="bootstrap_servers",
    ),
    "kafka_sasl_username": CredentialSpec(
        env_var="KAFKA_SASL_USERNAME",
        tools=KAFKA_TOOLS,
        required=False,
        startup_required=False,
        help_url="https://docs.confluent.io/platform/current/security/authentication.html",
        description="SASL username for Kafka authentication (required if using SASL)",
        aden_supported=False,
        direct_api_key_supported=True,
        api_key_instructions="SASL username - for Confluent Cloud, use the API Key",
        credential_id="kafka",
        credential_key="sasl_username",
    ),
    "kafka_sasl_password": CredentialSpec(
        env_var="KAFKA_SASL_PASSWORD",
        tools=KAFKA_TOOLS,
        required=False,
        startup_required=False,
        help_url="https://docs.confluent.io/platform/current/security/authentication.html",
        description="SASL password for Kafka authentication (required if using SASL)",
        aden_supported=False,
        direct_api_key_supported=True,
        api_key_instructions="SASL password - for Confluent Cloud, use the API Secret",
        credential_id="kafka",
        credential_key="sasl_password",
    ),
    "kafka_ssl_ca_location": CredentialSpec(
        env_var="KAFKA_SSL_CA_LOCATION",
        tools=KAFKA_TOOLS,
        required=False,
        startup_required=False,
        help_url="https://kafka.apache.org/documentation/#security_ssl",
        description="Path to CA certificate file for SSL/TLS verification",
        aden_supported=False,
        direct_api_key_supported=True,
        api_key_instructions="Path to the CA certificate file (PEM format) for SSL connections",
        credential_id="kafka",
        credential_key="ssl_ca_location",
    ),
    "kafka_security_protocol": CredentialSpec(
        env_var="KAFKA_SECURITY_PROTOCOL",
        tools=KAFKA_TOOLS,
        required=False,
        startup_required=False,
        help_url="https://kafka.apache.org/documentation/#security",
        description="Security protocol: PLAINTEXT, SSL, SASL_PLAINTEXT, or SASL_SSL",
        aden_supported=False,
        direct_api_key_supported=True,
        api_key_instructions="""Security protocol options:
- PLAINTEXT: No security (development only)
- SSL: TLS encryption
- SASL_PLAINTEXT: SASL auth without TLS
- SASL_SSL: SASL auth with TLS encryption (recommended)""",
        credential_id="kafka",
        credential_key="security_protocol",
    ),
}
