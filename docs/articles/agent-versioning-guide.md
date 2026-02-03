# Agent Versioning

Version control for agent graphs with semantic versioning, rollback, and A/B testing.

## Why Version Control?

Production agents change frequently. You need:
- Rollback when deployments break
- Compare what changed between versions
- A/B test new features before full rollout
- Audit trail of all changes

## Quick Start

```bash
# Save version
python -m core version save exports/my-agent -d "Initial release" -b patch

# List versions
python -m core version list my-agent

# Rollback
python -m core version rollback my-agent 1.0.0
```

## CLI Commands

### Save Version

```bash
python -m core version save <agent_path> -d "description" [-b patch|minor|major]
```

**Arguments:**
- `-d, --description`: What changed (required)
- `-b, --bump`: Version bump type (default: patch)
  - `patch`: Bug fixes (1.0.0 → 1.0.1)
  - `minor`: New features (1.0.0 → 1.1.0)
  - `major`: Breaking changes (1.0.0 → 2.0.0)
- `-t, --tag`: Optional tag name
- `--created-by`: Optional user identifier

### List Versions

```bash
python -m core version list <agent_id> [--json]
```

Shows all versions with descriptions, timestamps, and tags.

### Rollback

```bash
python -m core version rollback <agent_id> <version> [-e export_path]
```

Restores agent to specified version and updates `exports/` folder.

### Compare Versions

```bash
python -m core version diff <agent_id> <from_version> <to_version> [--json]
```

Shows added/removed/modified nodes, edges, and goal changes.

### Tag Management

```bash
python -m core version tag <agent_id> <version> <tag>
```

Common tags: `production`, `staging`, `stable`, `hotfix`

### A/B Testing

```bash
python -m core version ab-test <agent_id> <version_a> <version_b> \
    --split 0.5 --metrics response_time success_rate
```

Creates test configuration for traffic splitting between versions.

## Python API

### Basic Operations

```python
from framework.runner.versioning import AgentVersionManager
from framework.schemas.version import BumpType

manager = AgentVersionManager(".aden/versions")

# Save version
version = manager.save_version(
    agent_id="my-agent",
    graph=graph_spec,
    goal=goal,
    description="Bug fixes",
    bump=BumpType.PATCH
)

# Load version
version = manager.load_version("my-agent", "1.2.0")

# Rollback
graph, goal = manager.rollback("my-agent", "1.2.0")

# Compare
diff = manager.compare_versions("my-agent", "1.0.0", "1.1.0")

# Tag
manager.tag_version("my-agent", "1.2.0", "production")
version = manager.get_version_by_tag("my-agent", "production")
```

### AgentRunner Integration

```python
from framework.runner import AgentRunner

# Load specific version
runner = AgentRunner.load("exports/my-agent", version="1.2.0")
result = await runner.run(context)

# Load by tag
runner = AgentRunner.load_by_tag(agent_id="my-agent", tag="production")
result = await runner.run(context)
```

### A/B Testing

```python
from framework.runner.ab_testing import create_ab_test_session

# Create test
router = create_ab_test_session(
    agent_id="my-agent",
    version_a="1.2.0",
    version_b="1.3.0",
    traffic_split=0.5,
    metrics=["response_time", "success_rate"]
)

# Route request
version = router.route("user-123-request-456")
runner = AgentRunner.load("exports/my-agent", version=version)
result = await runner.run(context)

# Record metrics
router.record_execution(
    request_id="user-123-request-456",
    version=version,
    metrics={"response_time": 0.5, "success_rate": 1.0}
)

# Analyze
analysis = router.analyze_results(primary_metric="success_rate")
print(f"Winner: {analysis['winner']}, Confidence: {analysis['confidence']}")
```

## Storage

Versions stored in `.aden/versions/`:

```
.aden/versions/
  my-agent/
    registry.json           # Version list and tags
    versions/
      1.0.0.json
      1.1.0.json
    ab_tests/
      test_001.json
      test_001_results.json
```

## Semantic Versioning

**Format:** `MAJOR.MINOR.PATCH`

- **MAJOR**: Breaking changes (removed nodes, changed behavior)
- **MINOR**: New features, backward compatible
- **PATCH**: Bug fixes

## Workflows

### Production Deployment

```bash
# Before deploy
python -m core version save exports/my-agent -d "Release 1.3.0" -b minor
python -m core version tag my-agent 1.3.0 production

# If issues
python -m core version rollback my-agent 1.2.0
python -m core version tag my-agent 1.2.0 production
```

### Feature Testing

```bash
# Save experimental version
python -m core version save exports/my-agent -d "New feature X" -b minor -t experiment

# A/B test
python -m core version ab-test my-agent 1.2.0 1.3.0 --split 0.1

# If successful, promote
python -m core version tag my-agent 1.3.0 production
```

### Bug Fix Rollback

```bash
# Identify issue
python -m core version list my-agent
python -m core version diff my-agent 1.2.0 1.2.1

# Rollback
python -m core version rollback my-agent 1.2.0
```

## CI/CD Integration

```yaml
# .github/workflows/version.yml
- name: Version Agent
  run: |
    VERSION_TYPE="patch"
    [[ "${{ github.event.head_commit.message }}" == *"BREAKING"* ]] && VERSION_TYPE="major"
    [[ "${{ github.event.head_commit.message }}" == *"feat:"* ]] && VERSION_TYPE="minor"
    
    python -m core version save exports/my-agent \
      -d "${{ github.event.head_commit.message }}" \
      -b $VERSION_TYPE
```
