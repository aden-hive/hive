# AWS CloudWatch Tool

Query Amazon CloudWatch metrics, alarms, and Logs Insights using AWS Signature V4
authentication. Signs requests by hand with `httpx` (no `boto3` dependency), following
the existing `aws_s3_tool` convention.

## Tools

| Tool | Description |
|------|-------------|
| `cloudwatch_list_metrics` | Discover available metrics for a namespace |
| `cloudwatch_get_metric_statistics` | Fetch datapoints for a metric over a time range |
| `cloudwatch_list_alarms` | List alarms filtered by state (OK / ALARM / INSUFFICIENT_DATA) |
| `cloudwatch_start_logs_query` | Start a Logs Insights query, returns a `query_id` |
| `cloudwatch_get_query_results` | Poll results for a running Logs Insights query |

## Setup

Set the following environment variables:

| Variable | Description |
|----------|-------------|
| `AWS_ACCESS_KEY_ID` | AWS access key |
| `AWS_SECRET_ACCESS_KEY` | AWS secret key |
| `AWS_REGION` | AWS region (default: `us-east-1`) |

Minimum IAM permissions: `cloudwatch:ListMetrics`, `cloudwatch:GetMetricStatistics`,
`cloudwatch:DescribeAlarms`, `logs:StartQuery`, `logs:GetQueryResults`.

Get credentials at: [AWS Console](https://console.aws.amazon.com/iam/)

## Usage Examples

### List metrics for EC2
```python
cloudwatch_list_metrics(namespace="AWS/EC2", metric_name="CPUUtilization")
```

### Get CPU statistics for an instance
```python
cloudwatch_get_metric_statistics(
    namespace="AWS/EC2",
    metric_name="CPUUtilization",
    start_time="2026-07-13T00:00:00Z",
    end_time="2026-07-13T01:00:00Z",
    period=300,
    statistics="Average,Maximum",
    dimension_name="InstanceId",
    dimension_value="i-1234567890abcdef0",
)
```

### List alarms currently firing
```python
cloudwatch_list_alarms(state="ALARM")
```

### Run a Logs Insights query
```python
qid = cloudwatch_start_logs_query(
    log_group="/aws/lambda/my-func",
    query="fields @timestamp, @message | sort @timestamp desc | limit 20",
    start_time=1752364800,
    end_time=1752368400,
)["query_id"]
cloudwatch_get_query_results(query_id=qid)  # poll until status == "Complete"
```

## Error Handling

All tools return error dicts on failure:
```python
{"error": "AWS_ACCESS_KEY_ID and AWS_SECRET_ACCESS_KEY are required", "help": "..."}
{"error": "HTTP 400: <ErrorResponse>...</ErrorResponse>"}
{"error": "CloudWatch request failed: <reason>"}
```
