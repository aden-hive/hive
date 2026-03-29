"""
Apache Kafka (Confluent REST Proxy) credentials.

Contains credentials for the Kafka REST Proxy API.
Requires KAFKA_REST_URL and KAFKA_CLUSTER_ID. Optional KAFKA_API_KEY + KAFKA_API_SECRET.
"""

from .base import CredentialSpec

KAFKA_CREDENTIALS = {
    "kafka_rest_url": CredentialSpec(
        env_var="KAFKA_REST_URL",
        tools=[
            "kafka_list_topics",
            "kafka_get_topic",
            "kafka_create_topic",
            "kafka_produce_message",
            "kafka_list_consumer_groups",
            "kafka_get_consumer_group_lag",
        ],
        required=True,
        startup_required=False,
        help_url="https://docs.confluent.io/platform/current/kafka-rest/index.html",
        description="Kafka REST Proxy URL (e.g. 'https://pkc-xxxxx.region.confluent.cloud:443')",
        direct_api_key_supported=True,
        api_key_instructions="""To set up Kafka REST Proxy access:
1. Get your REST Proxy URL (Confluent Cloud: cluster settings; self-hosted: default port 8082)
2. Get your cluster ID from cluster settings
3. Create an API key pair (Confluent Cloud) or configure SASL auth
4. Set environment variables:
   export KAFKA_REST_URL=https://your-rest-proxy-url
   export KAFKA_CLUSTER_ID=your-cluster-id
   export KAFKA_API_KEY=your-api-key (optional)
   export KAFKA_API_SECRET=your-api-secret (optional)""",
        health_check_endpoint="",
        credential_id="kafka_rest_url",
        credential_key="api_key",
    ),
    "kafka_cluster_id": CredentialSpec(
        env_var="KAFKA_CLUSTER_ID",
        tools=[
            "kafka_list_topics",
            "kafka_get_topic",
            "kafka_create_topic",
            "kafka_produce_message",
            "kafka_list_consumer_groups",
            "kafka_get_consumer_group_lag",
        ],
        required=True,
        startup_required=False,
        help_url="https://docs.confluent.io/platform/current/kafka-rest/index.html",
        description="Kafka cluster ID",
        direct_api_key_supported=True,
        api_key_instructions="""See KAFKA_REST_URL instructions above.""",
        health_check_endpoint="",
        credential_id="kafka_cluster_id",
        credential_key="api_key",
    ),
}
