# AWS CloudWatch Toolkit

Native integration with AWS CloudWatch for Hive agent observability and monitoring.

## Overview
The CloudWatch toolkit enables agents to publish custom metrics, stream execution logs, and manage alarms directly within the AWS ecosystem. This is essential for production deployments where teams need centralized monitoring and alerting.

## Requirements
- `boto3` Python library
- AWS Credentials with CloudWatch permissions (`CloudWatchFullAccess` or scoped permissions)

## Configuration
Requires the following environment variables or credentials in the store:
- `AWS_ACCESS_KEY_ID`: AWS access key
- `AWS_SECRET_ACCESS_KEY`: AWS secret key
- `AWS_REGION`: AWS region (defaults to `us-east-1`)

## Available Tools

### Metrics
- `cloudwatch_put_metric`: Publish custom metrics (e.g., execution time, token usage, cost).
- `cloudwatch_get_metric_stats`: Retrieve metric statistics for self-monitoring and adaptive behavior.

### Logs
- `cloudwatch_put_log_event`: Stream log events to CloudWatch Logs (auto-creates log groups/streams).

### Alarms
- `cloudwatch_create_alarm`: Create or update CloudWatch Alarms with configurable thresholds and actions.

## Usage Examples

### Publishing a Metric
```python
cloudwatch_put_metric(
    namespace="HiveAgents",
    metric_name="ExecutionDuration",
    value=45.2,
    unit="Seconds",
    dimensions={"AgentID": "invoice-processor-01"}
)
```

### Sending a Log Event
```python
cloudwatch_put_log_event(
    log_group="/hive/agents/production",
    log_stream="invoice-processor-01",
    message="Agent started node: validate_schema"
)
```

### Creating an Alarm
```python
cloudwatch_create_alarm(
    alarm_name="HighTokenUsageAlarm",
    namespace="HiveAgents",
    metric_name="TokensUsed",
    threshold=50000.0,
    comparison_operator="GreaterThanThreshold",
    alarm_actions=["arn:aws:sns:us-east-1:123456789012:MyAlertTopic"]
)
```

## Setup Instructions
1. Ensure your AWS user/role has `cloudwatch:PutMetricData`, `cloudwatch:PutMetricAlarm`, `logs:CreateLogGroup`, `logs:CreateLogStream`, and `logs:PutLogEvents` permissions.
2. Set your AWS credentials in the environment or use the Hive credential manager.
